import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { Pool } from 'pg'
import { Counter, Gauge, Histogram } from 'prom-client'

import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import {
    StepResume,
    WorkflowStepResumeSchema,
    counterStepResume,
    processStepResumes,
} from '~/cdp/services/hogflows/step-resume.service'
import { parseWorkflowStepDispatchKey } from '~/cdp/utils/workflow-step-dispatch-key'
import {
    KAFKA_CDP_INTERNAL_EVENTS,
    KAFKA_COHORT_MEMBERSHIP_CHANGED,
    KAFKA_EVENTS_JSON,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
} from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, START_AT_LATEST, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { sanitizeJsonbValue } from '~/common/utils/db/utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { isValidTeamId } from '~/common/utils/team-manager'
import { UUIDT } from '~/common/utils/utils'

import {
    ClickHousePerson,
    ClickHousePersonDistinctId2,
    HealthCheckResult,
    PluginsServerConfig,
    RawClickHouseEvent,
    Team,
} from '../../types'
import { CdpInternalEventSchema } from '../schema'
import { COHORT_MEMBERSHIP_CHANGED_EVENT } from '../services/cohorts/cohort-membership-repository'
import { decodeJobState } from '../services/cyclotron-v2/job-codec'
import { createCyclotronPool } from '../services/cyclotron-v2/pg-pool'
import { MAX_CONVERSION_WINDOW_MINUTES, pinConversionGoal } from '../services/hogflows/conversion-watcher'
import {
    hasEventOrActionTarget,
    matchesWaitUntilCondition,
    runFilterBytecode,
} from '../services/hogflows/hogflow-utils'
import {
    CyclotronPerson,
    HogFlowInvocationContext,
    HogFunctionInvocationGlobals,
    MinimalAppMetric,
    PinnedConversionGoal,
} from '../types'
import {
    convertInternalEventToHogFunctionInvocationGlobals,
    convertToHogFunctionInvocationGlobals,
    getPersonDisplayName,
} from '../utils'
import { BatchCoalescer } from '../utils/batch-coalescer'
import { convertToHogFunctionFilterGlobal, rejectsEventName } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { convertCohortMembershipChangeToGlobals } from './cdp-cohort-membership-trigger.consumer'
import { CohortMembershipChangeSchema, isCohortMembershipControlRecord } from './cdp-cohort-membership.consumer'
import { ParseBatchOptions, parseBatch, readTeamIdHeader, skipIfMalformed } from './message-parsing'
import { counterTeamIdHeaderMismatch, counterTeamIdSource } from './metrics'

// A waker only needs signals that arrive after a job parks, never history. auto.offset.reset=latest
// makes a fresh consumer group start at the tip instead of replaying the (unconsumable at prod
// volume) topic backlog. Once the group has committed offsets, both consumer impls resume from them
// regardless of this value — so steady-state recovery is committed-offset resume; latest only governs
// the first bootstrap and offset-loss edge cases (covered by the deferred lag alerting follow-up).
const startAtLatest = START_AT_LATEST

// How stale the has-live-watchers gate may be. A team that just enrolled its first run while its only
// goal flow was already paused waits at most this long to be admitted. Each refresh reads every
// watcher row, and every pod runs it, so a short interval costs the database more than the lookups do.
// A flow change admits its team for an hour on its own, which covers that case well inside this.
const WATCHER_TEAMS_REFRESH_INTERVAL_MS = 5 * 60 * 1000
// A failed refresh leaves the gate on a stale or empty set, so it is retried this soon instead.
const WATCHER_TEAMS_REFRESH_RETRY_MS = 30_000
// Covers how long a worker can keep running a flow version after it was replaced.
const PINNED_GOAL_CACHE_LAG_MS = 60 * 60 * 1000
// When the last successful goals read is older than this, every event of a team with goals is looked up.
const PINNED_GOALS_MAX_READ_AGE_MS = 5 * 60 * 1000
// A worker can start a run on a flow version for a while after the save that replaced it.
const PINNED_GOALS_WINDOW_MARGIN_MS = 24 * 60 * 60 * 1000
// After a flow change, its team looks up every event until a goals read that started this long after the change,
// so the replica the goals are read from has caught up with the save.
const PINNED_GOALS_CHANGE_WINDOW_MS = 2 * 60 * 1000
// The pool sets no query timeout, so without this one a read on a dead connection would block every later read.
const PINNED_GOALS_READ_TIMEOUT_MS = 20_000
// Past this many goals, a team looks up every event rather than running each goal against it.
const PINNED_GOALS_MAX_PER_TEAM = 500

const counterHogflowMatcherCandidatesEvaluated = new Counter({
    name: 'cdp_hogflow_matcher_candidates_evaluated',
    help: 'Parked hogflow jobs the matcher loaded from cyclotron and evaluated against a batch.',
})

const counterHogflowMatcherJobsWoken = new Counter({
    name: 'cdp_hogflow_matcher_jobs_woken',
    help: 'Parked hogflow jobs the matcher woke because an incoming event matched.',
})

const counterHogflowMatcherConversionsCounted = new Counter({
    name: 'cdp_hogflow_matcher_conversions_counted',
    help: "Conversions counted by claiming a run's watcher row. Deleting the row is the claim, so a run counts at most once however many matching events arrive.",
})

// A person merge repoints the merged-away person's distinct_ids at the survivor. A wait parked while
// that distinct_id belonged to the old person still references the old person_id, so the survivor's
// person/event updates (keyed on the new id) can't wake it. We re-key such waits onto the survivor;
// this counts the re-keyed jobs.
const counterHogflowMatcherPendingWakesRecorded = new Counter({
    name: 'cdp_hogflow_matcher_pending_wakes_recorded_total',
    help: 'Wait wakes recorded on jobs a worker held, so the worker wakes the job when it parks.',
})

const counterHogflowMatcherJobsRekeyedOnMove = new Counter({
    name: 'cdp_hogflow_matcher_jobs_rekeyed_on_distinct_id_move',
    help: 'Parked wait_until_condition jobs re-keyed to the surviving person after a distinct_id was repointed by a merge.',
})

// A wait parked before its distinct_id had a person keeps a null person_id, and person wakes are keyed on
// person_id alone, so nothing can ever wake it — only the polling re-check advances it. The distinct_id's
// first mapping (version 0) is where that anchor becomes available. 'seen' is every first mapping admitted
// for a team with a wait flow, which is the load this path adds; 'filled' is the jobs it actually anchored.
// A 'seen' rate far above 'filled' is expected — watch the gap for query cost, not correctness.
const counterHogflowMatcherFirstMapping = new Counter({
    name: 'cdp_hogflow_matcher_first_mapping_total',
    help: 'distinct_id first mappings processed for parked waits with no person anchor, by outcome.',
    labelNames: ['outcome'],
})

const counterHogflowMatcherWatchersRekeyed = new Counter({
    name: 'cdp_hogflow_matcher_watchers_rekeyed',
    help: 'Conversion watchers repointed onto a merge survivor. Without this they would be addressed to a person no update will ever mention again.',
})

const counterHogflowMatcherConversionEventSkipped = new Counter({
    name: 'cdp_hogflow_matcher_conversion_event_skipped',
    help: 'Conversions counted as a metric but not emitted as $workflows_conversion, because the run had no distinct_id to attribute a capture event to.',
})

const counterHogflowMatcherWatchersSkipped = new Counter({
    name: 'cdp_hogflow_matcher_watchers_skipped',
    help: 'Watcher rows skipped because their pinned goal was missing or unreadable. Each one is a run that can never record a conversion.',
})

const counterHogflowMatcherWatchersEvaluated = new Counter({
    name: 'cdp_hogflow_matcher_watchers_evaluated',
    help: 'Conversion watcher rows loaded and evaluated against a batch.',
})

const gaugeHogflowMatcherTeamsWithWatchers = new Gauge({
    name: 'cdp_hogflow_matcher_teams_with_live_watchers',
    help: 'Teams admitted through the parse gate purely because they still have unexpired conversion watchers.',
})

const gaugeHogflowMatcherPinnedGoalsInUse = new Gauge({
    name: 'cdp_hogflow_matcher_pinned_goals_in_use',
    help: '1 while the goal lookups are gated on fresh conversion goals, 0 otherwise.',
})

const counterHogflowMatcherWatcherEventsSkipped = new Counter({
    name: 'cdp_hogflow_matcher_watcher_events_skipped',
    help: 'Events left out of the conversion_watchers lookup because no conversion goal of their team can match their name.',
})

const counterHogflowMatcherFilterFirstEvents = new Counter({
    name: 'cdp_hogflow_matcher_filter_first_events',
    help: 'Events checked against the workflow filters before a lookup, by whether they pass and are looked up.',
    labelNames: ['lookup', 'result'],
})

const counterHogflowMatcherFilterFirstMissed = new Counter({
    name: 'cdp_hogflow_matcher_filter_first_missed',
    help: 'Wakes or conversions caused by an event that failed the filter check. Must stay at zero before the check skips lookups.',
    labelNames: ['lookup'],
})

const histogramHogflowMatcherFindWatchers = new Histogram({
    name: 'cdp_hogflow_matcher_find_watchers_seconds',
    help: 'Duration of the conversion_watchers lookup.',
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

// Latency of the cyclotron lookup for parked jobs. Watch this for cyclotron-node
// read pressure as the wait-until-event feature ramps.
const histogramHogflowMatcherFindParkedJobs = new Histogram({
    name: 'cdp_hogflow_matcher_find_parked_jobs_seconds',
    help: 'Duration of the findParkedJobs cyclotron query.',
    labelNames: ['stream'],
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

// Which Kafka stream a batch came from. Labels the find_parked_jobs metric so the person and
// internal-event query load is distinguishable from the events firehose on the shared cyclotron DB.
type WakeSource = 'events' | 'person' | 'internal_events' | 'cohort_membership'

type FilterFirstMode = 'off' | 'shadow' | 'on'

// eventNames: every event name the goal can match, or null when it can match any.
type PinnedGoalEntry = { functionId: string; goal: PinnedConversionGoal; key: string; eventNames: Set<string> | null }

// Past this, the rest of a batch is looked up without the check, so slow or numerous filters cannot hold the batch.
const FILTER_FIRST_BUDGET_MS = 50

// A filter that draws a random number can pass one evaluation and fail the next, so checking it before the
// lookup would make it pass twice to count.
function callsRandom(bytecode: unknown): boolean {
    return Array.isArray(bytecode) && (bytecode.includes('randomFloat') || bytecode.includes('generateUUIDv4'))
}

function parseFilterFirstMode(
    value: string,
    setting = 'CDP_HOGFLOW_SUBSCRIPTION_MATCHER_FILTER_FIRST'
): FilterFirstMode {
    if (value === 'off' || value === 'shadow' || value === 'on') {
        return value
    }
    throw new Error(`${setting} must be off, shadow or on, got "${value}"`)
}

export const counterHogflowMatcherEventSkipped = new Counter({
    name: 'cdp_hogflow_matcher_event_skipped',
    help: 'An incoming event was dropped before matching: no identifiers (distinct_id or person_id), an invalid team id, unknown team, a backfilled cohort membership change, or a captured event that uses the reserved cohort membership event name.',
    labelNames: ['reason'],
})

type ParkedCandidate = {
    id: string
    teamId: number
    functionId: string
    parentRunId: string | null
    actionId: string | null
    distinctId: string | null
    personId: string | null
    scheduledAt: number
    status: 'available' | 'running'
}

type PendingWakeWrite = {
    id: string
    wakes: Record<
        string,
        { kind: 'match' | 'recheck'; eventName?: string; eventUuid?: string; eventTimestamp?: string }
    >
}

// A distinct_id repointed by a merge: the distinct_id and the survivor person it now resolves to.
// version orders repoints for the same distinct_id — the highest wins when a batch carries several.
type PersonDistinctIdMove = {
    teamId: number
    distinctId: string
    newPersonId: string
    version: number
}

// A parked job the matcher needs to act on this batch: either resume it (stepMatched, or a
// conversion match on an exit-on-conversion flow) and/or count its conversion once. Carries the
// fields needed to emit the `conversion` metric without re-reading the hogflow.
// Filter types that read the trigger event or the run's own variables. Neither changes while the run
// waits, so a person change cannot move a term of these types.
const PERSON_INDEPENDENT_FILTER_TYPES = new Set([
    'event',
    'event_metadata',
    'meta',
    'element',
    'feature',
    'session',
    'workflow_variable',
    'group',
])

// A person wake carries a synthetic $person_updated event with no properties and no workflow
// variables, so anything but a pure person-property condition reads as false here and would strand
// the wait until its ceiling. Wake the job and let the worker, which holds the run's own globals, decide.
// A condition with no term a person change can move is left alone: the worker would only re-park it.
function conditionNeedsRunGlobals(action: Extract<HogFlowAction, { type: 'wait_until_condition' }>): boolean {
    const filters = action.config.condition?.filters
    const properties = Array.isArray(filters?.properties) ? filters.properties : []
    // An event or action selector reads the run's event, like an event property does.
    const selectsEvent = [filters?.events, filters?.actions].some((list) => Array.isArray(list) && list.length > 0)
    const types: (string | undefined)[] = properties.map((p: { type?: string }) => p?.type)
    return (
        (selectsEvent || types.some((t) => t !== 'person')) &&
        types.some((t) => !PERSON_INDEPENDENT_FILTER_TYPES.has(t ?? ''))
    )
}

type MatchedJob = {
    id: string
    actionId: string | null
    teamId: number
    functionId: string
    parentRunId: string | null
    stepMatched: boolean
    // The matcher could not decide this wait, so it wakes the job and lets the worker evaluate.
    recheckMatched: boolean
    conversionMatched: boolean
    exitsOnConversion: boolean
    // Name, UUID and timestamp of the matched event, so the resume log can name it and link to it.
    eventName?: string
    eventUuid?: string
    eventTimestamp?: string
    // Distinct id + name/uuid of the event that satisfied the conversion goal, so the matcher can
    // emit the `$workflows_conversion` PostHog event for the converting person.
    conversionDistinctId?: string
    conversionEventName?: string
    conversionEventUuid?: string
}

type FilterGlobals = ReturnType<typeof convertToHogFunctionFilterGlobal>

// Emitted by Django when a run a workflow step dispatched ends; `origin_key` names the parked job.
export const WORKFLOW_STEP_RESUME_EVENT = '$workflow_step_resume'

// Wakes parked hogflow jobs when an event matches a `wait_until_condition` step
// or a workflow conversion goal.
export class CdpHogflowSubscriptionMatcherConsumer<
    TConfig extends PluginsServerConfig = PluginsServerConfig,
> extends CdpConsumerBase<TConfig> {
    protected name = 'CdpHogflowSubscriptionMatcherConsumer'
    protected kafkaConsumer: KafkaConsumerInterface
    // clickhouse_person carries non-event person-property changes (the precalculated topic only
    // emits a per-condition match boolean, not the full property set the wait bytecode needs).
    private personKafkaConsumer: KafkaConsumerInterface
    // cdp_internal_events carries CDP-generated signals (e.g. $insight_alert_firing,
    // $activity_log_entry_created) that bypass the public capture pipeline and never reach the
    // analytics events topic. (Email engagement events, by contrast, flow through capture to
    // clickhouse_events_json and are already covered by the events stream.)
    private internalEventsKafkaConsumer: KafkaConsumerInterface
    // clickhouse_person_distinct_id carries distinct_id → person repoints (version > 0). A merge moves the
    // merged-away person's distinct_ids onto the survivor here; we consume it to re-key parked waits onto
    // the survivor's id so the survivor's person/event updates can wake them.
    private personDistinctIdKafkaConsumer: KafkaConsumerInterface
    // realtime_only_events_json carries the $feature_flag_called events that ingestion stops writing to
    // clickhouse_events_json for a FLAG_EVALUATIONS_ONLY organization.
    private realtimeOnlyEventsKafkaConsumer?: KafkaConsumerInterface
    // cohort_membership_changed carries realtime cohort joins and leaves. Each one becomes a
    // `$cohort_membership_changed` event, so event waits and event conversion goals can match it.
    private cohortMembershipKafkaConsumer: KafkaConsumerInterface
    private cyclotronPool: Pool
    private watcherTeamsRefreshTimer: NodeJS.Timeout | null = null
    // Teams with at least one unexpired watcher. Empty until the first refresh, which start() awaits
    // before consuming, so the gate is never consulted against an unpopulated set.
    // Team -> workflow id -> when its oldest unexpired watcher was created.
    private liveWatcherFlowsByTeam: Map<number, Map<string, number>> = new Map()
    // A worker still running the old version can write a watcher for some time after the change.
    private teamsWithChangedFlows: Map<number, { refreshNumber: number; at: number }> = new Map()
    private watcherRefreshNumber = 0
    private watcherRefreshedAt = 0
    private pinnedGoalsMode: FilterFirstMode
    private postgres: PostgresRouter
    // Every goal a workflow has had live, read from workflows_hogflowconversiongoal, by team.
    private pinnedGoalsByTeam: Map<number, Map<string, PinnedGoalEntry>> = new Map()
    private pinnedGoalsRead: Promise<void> | null = null
    private watcherScan: Promise<void> | null = null
    private teamsOverGoalCap: Set<number> = new Set()
    private pinnedGoalsReadAt = 0
    // Team -> when one of its flows changed, until a goals read that started PINNED_GOALS_CHANGE_WINDOW_MS later.
    private pinnedGoalChanges: Map<number, number> = new Map()
    // "on" and the goals have been read once. From then on the full watcher scan no longer runs.
    private usingPinnedGoals = false
    // An events batch carries few events a flow can act on, so most lookups cost a query for little.
    private eventWakes: BatchCoalescer<HogFunctionInvocationGlobals>
    private eventArrivals = new WeakMap<HogFunctionInvocationGlobals, Date>()
    private filterFirst: FilterFirstMode

    constructor(config: TConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.filterFirst = parseFilterFirstMode(config.CDP_HOGFLOW_SUBSCRIPTION_MATCHER_FILTER_FIRST)
        this.postgres = deps.postgres
        this.pinnedGoalsMode = parseFilterFirstMode(
            config.CDP_HOGFLOW_SUBSCRIPTION_MATCHER_PINNED_GOALS,
            'CDP_HOGFLOW_SUBSCRIPTION_MATCHER_PINNED_GOALS'
        )
        this.eventWakes = new BatchCoalescer(
            (globals) => this.processBatch(globals, 'events', (g) => this.eventArrivals.get(g)),
            config.CDP_HOGFLOW_SUBSCRIPTION_MATCHER_EVENTS_COALESCE_MS,
            config.CONSUMER_MAX_BACKGROUND_TASKS
        )
        deps.pubSub.on<{ teamId: number }>('reload-hog-flows', ({ teamId }) => {
            if (!this.usingPinnedGoals) {
                this.teamsWithChangedFlows.set(teamId, { refreshNumber: this.watcherRefreshNumber, at: Date.now() })
            }
            if (this.pinnedGoalsMode !== 'off') {
                this.pinnedGoalChanges.set(teamId, Date.now())
            }
        })
        this.kafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-consumer',
                topic: KAFKA_EVENTS_JSON,
            },
            startAtLatest
        )
        this.personKafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-person-consumer',
                topic: KAFKA_PERSON,
            },
            startAtLatest
        )
        this.internalEventsKafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-internal-events-consumer',
                topic: KAFKA_CDP_INTERNAL_EVENTS,
            },
            {
                ...startAtLatest,
                ...(config.CDP_INTERNAL_EVENTS_CONSUMER_METADATA_BROKER_LIST
                    ? { 'metadata.broker.list': config.CDP_INTERNAL_EVENTS_CONSUMER_METADATA_BROKER_LIST }
                    : {}),
            }
        )
        this.personDistinctIdKafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-person-distinct-id-consumer',
                topic: KAFKA_PERSON_DISTINCT_ID,
            },
            startAtLatest
        )
        this.cohortMembershipKafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-cohort-membership-consumer',
                topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
            },
            startAtLatest
        )
        if (config.CDP_HOGFLOW_SUBSCRIPTION_MATCHER_REALTIME_ONLY_EVENTS_TOPIC) {
            this.realtimeOnlyEventsKafkaConsumer = createKafkaConsumer(
                {
                    groupId: 'cdp-hogflow-subscription-matcher-realtime-only-events-consumer',
                    topic: config.CDP_HOGFLOW_SUBSCRIPTION_MATCHER_REALTIME_ONLY_EVENTS_TOPIC,
                },
                startAtLatest
            )
        }

        // The matcher does nothing but read/write cyclotron_jobs, so a missing connection
        // string means it would silently consume the event stream and wake nothing. Fail
        // loudly on startup instead of degrading into a healthy-looking no-op.
        if (!config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CdpHogflowSubscriptionMatcherConsumer requires CYCLOTRON_NODE_DATABASE_URL')
        }
        this.cyclotronPool = createCyclotronPool('subscription_matcher', {
            connectionString: config.CYCLOTRON_NODE_DATABASE_URL,
            max: config.CYCLOTRON_NODE_MAX_CONNECTIONS,
        })
    }

    // An event counts against a wait or goal only if it arrived before that wait's deadline or that goal's
    // expiry, so holding it for a lookup neither costs nor earns a wake or conversion.
    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[],
        source: WakeSource = 'events',
        arrivalOf?: (globals: HogFunctionInvocationGlobals) => Date | undefined
    ): Promise<void> {
        if (!invocationGlobals.length) {
            return
        }
        try {
            const now = new Date()
            await this.wakeMatchingWorkflows(invocationGlobals, source, (g) => arrivalOf?.(g) ?? now)
        } finally {
            // Flush any `conversion` metrics and `$workflows_conversion` events queued during matching.
            // Best-effort: a flush failure must not crash the batch (which would replay the event
            // offsets). flush() is a no-op when nothing was queued, so it's safe to call unconditionally.
            await instrumentFn({ key: 'cdp.background_task.monitoring_flush', sendException: false }, async () => {
                try {
                    await Promise.all([
                        this.hogFunctionMonitoringService.flush(),
                        this.invocationResultsService.capturedEventsService.flush(),
                    ])
                } catch (err) {
                    logger.error('⚠️', 'Failed to flush hogflow matcher app metrics/events', { err })
                    captureException(err)
                }
            })
        }
    }

    @instrumented('cdpHogflowSubscriptionMatcher.wakeMatchingWorkflows')
    private async wakeMatchingWorkflows(
        invocationGlobals: HogFunctionInvocationGlobals[],
        source: WakeSource,
        arrivedAt: (globals: HogFunctionInvocationGlobals) => Date
    ): Promise<void> {
        // The lookups take the earliest arrival, then each candidate keeps only the events that beat it.
        const earliestArrival = new Date(Math.min(...invocationGlobals.map((g) => arrivedAt(g).getTime())))
        const indexed = indexBatch(invocationGlobals)
        const { teamIds } = indexed
        if (indexed.byDistinctId.size === 0 && indexed.byPersonId.size === 0) {
            return
        }

        // Compute filterGlobals once per event; the same event can match many candidates and many
        // watchers.
        const filterGlobalsByEvent = new Map<HogFunctionInvocationGlobals, FilterGlobals>()
        const filterGlobalsFor = (g: HogFunctionInvocationGlobals): FilterGlobals => {
            let fg = filterGlobalsByEvent.get(g)
            if (!fg) {
                fg = convertToHogFunctionFilterGlobal(g)
                filterGlobalsByEvent.set(g, fg)
            }
            return fg
        }

        // A cohort membership change carries no person properties. A filter that reads the person would see
        // an empty person, so a negative filter such as "is not set" would match. Such a change is judged
        // only by event entries that do not read the person.
        const eventsOnly = source === 'cohort_membership'
        const hogFlowsByTeam = await this.hogFlowManager.getHogFlowsForTeams(teamIds)

        // Claimed before the parked-job work and independently of it: a watcher's run may have
        // finished long ago, so gating this on the flow still having something parked would put back
        // exactly the blind spot watchers exist to remove. Only a goal flow's run writes a watcher.
        const usePinnedGoals = this.usingPinnedGoals
        const shadowPinnedGoals = !usePinnedGoals && this.pinnedGoalsMode !== 'off' && this.pinnedGoalsFresh()
        const goalFlowsByTeam = new Map<number, HogFlow[] | 'any'>()
        const pinnedGoalsByTeam = new Map<number, PinnedGoalEntry[] | 'any'>()
        for (const teamId of teamIds) {
            const flows = hogFlowsByTeam[teamId] ?? []
            if (!(this.mayHaveLiveWatchers(teamId) || flows.some(hasConversionGoal))) {
                continue
            }
            if (!usePinnedGoals) {
                goalFlowsByTeam.set(teamId, this.goalFlowsForWatchers(teamId, flows))
            }
            if (usePinnedGoals || shadowPinnedGoals) {
                pinnedGoalsByTeam.set(teamId, this.pinnedGoalsForTeam(teamId, flows))
            }
        }
        // Every event of a team with goals goes on to the check, which compares event names and runs the goals.
        const watcherGlobals = usePinnedGoals
            ? invocationGlobals.filter((globals) => pinnedGoalsByTeam.has(globals.project.id))
            : invocationGlobals.filter((globals) => {
                  const goalFlows = goalFlowsByTeam.get(globals.project.id)
                  return (
                      goalFlows === 'any' || goalFlows?.some((flow) => goalAdmitsEventName(flow, globals.event.event))
                  )
              })
        counterHogflowMatcherWatcherEventsSkipped.inc(
            invocationGlobals.filter((globals) =>
                (usePinnedGoals ? pinnedGoalsByTeam : goalFlowsByTeam).has(globals.project.id)
            ).length - watcherGlobals.length
        )
        // Mirrors the claim below, which judges a watcher by its own pinned goal against the same globals: no
        // pinned goal matching means no watcher can convert on this event.
        const couldMeetPinnedGoal = (
            globals: HogFunctionInvocationGlobals,
            spent: () => boolean
        ): boolean | Promise<boolean> => {
            const entries = pinnedGoalsByTeam.get(globals.project.id)
            return (
                entries === 'any' ||
                couldMatchPinnedGoals(entries ?? [], globals.event.event, filterGlobalsFor(globals), eventsOnly, spent)
            )
        }
        // Only the events stream is checked against the flows: a person change or a cohort change is judged
        // against state the event does not carry, and internal events are too few to matter.
        const filterFirst = source === 'events' ? this.filterFirst : 'off'
        let watcherCheck
        if (usePinnedGoals) {
            watcherCheck = await this.checkFilters('on', 'watcher_goals', watcherGlobals, couldMeetPinnedGoal)
        } else {
            const flowCheck = await this.checkFilters(filterFirst, 'watchers', watcherGlobals, (globals, spent) => {
                const goalFlows = goalFlowsByTeam.get(globals.project.id)
                // A live watcher can only hold the goal of its flow as cached, unless the team is 'any'.
                return goalFlows === 'any' || couldConvert(goalFlows ?? [], filterGlobalsFor(globals), spent)
            })
            watcherCheck = flowCheck
            if (shadowPinnedGoals) {
                const shadowCheck = await this.checkFilters(
                    'shadow',
                    'watcher_goals',
                    flowCheck.lookup,
                    couldMeetPinnedGoal
                )
                watcherCheck = {
                    lookup: flowCheck.lookup,
                    noteMatch: (globals: HogFunctionInvocationGlobals) => {
                        flowCheck.noteMatch(globals)
                        shadowCheck.noteMatch(globals)
                    },
                }
            }
        }
        if (watcherCheck.lookup.length > 0) {
            const conversionsCounted = await this.claimConversionWatchers(
                indexBatch(watcherCheck.lookup),
                filterGlobalsFor,
                eventsOnly,
                earliestArrival,
                arrivedAt,
                watcherCheck.noteMatch
            )
            counterHogflowMatcherConversionsCounted.inc(conversionsCounted)
        }

        // Build the set of actionable flows from the in-memory hogflow cache (same pattern as
        // cdp-events). Only flows with a wait_until_condition step or an event-based conversion
        // goal can ever be woken; scoping to them keeps the function_id list in findParkedJobs
        // small and skips cyclotron entirely when a batch has none.
        const hogflows: Record<string, HogFlow> = {}
        for (const flows of Object.values(hogFlowsByTeam)) {
            for (const flow of flows) {
                if (hasWaitUntilOrConversion(flow)) {
                    hogflows[flow.id] = flow
                }
            }
        }

        if (Object.keys(hogflows).length === 0) {
            return
        }

        const actionableFlowsByTeam = new Map<number, HogFlow[]>()
        const actionableFlowsOf = (teamId: number): HogFlow[] => {
            let flows = actionableFlowsByTeam.get(teamId)
            if (!flows) {
                flows = (hogFlowsByTeam[teamId] ?? []).filter(hasWaitUntilOrConversion)
                actionableFlowsByTeam.set(teamId, flows)
            }
            return flows
        }
        const parkedCheck = await this.checkFilters(filterFirst, 'parked', invocationGlobals, (globals, spent) =>
            this.couldMoveRun(actionableFlowsOf(globals.project.id), filterGlobalsFor(globals), spent)
        )
        if (parkedCheck.lookup.length === 0) {
            return
        }
        const { distinctTeamIds, distinctIds, personTeamIds, personIds, byDistinctId, byPersonId } =
            parkedCheck.lookup === invocationGlobals ? indexed : indexBatch(parkedCheck.lookup)

        const candidates = await this.findParkedJobs(
            distinctTeamIds,
            distinctIds,
            personTeamIds,
            personIds,
            Object.keys(hogflows),
            source,
            earliestArrival
        )
        if (candidates.length === 0) {
            return
        }
        counterHogflowMatcherCandidatesEvaluated.inc(candidates.length)

        const matchedJobs: MatchedJob[] = []
        const pendingWakes: PendingWakeWrite[] = []
        // Runs of one flow for one person see the same events, so each wait is judged once per person.
        const waitWakes = new Map<string, Promise<PendingWakeWrite['wakes'][string] | null>>()
        for (const candidate of candidates) {
            const hogflow = hogflows[candidate.functionId]
            if (!hogflow) {
                continue
            }

            // A held job's scheduled time is already past, and an event that arrives during the hold still counts.
            const candidateGlobals = collectCandidateGlobals(candidate, byDistinctId, byPersonId).filter(
                (globals) => candidate.status === 'running' || arrivedAt(globals).getTime() < candidate.scheduledAt
            )
            if (candidateGlobals.length === 0) {
                continue
            }

            // A worker holds this job, so it may be about to park on any of the flow's waits.
            if (candidate.status === 'running') {
                // Step ids are user-chosen strings, so these maps have no prototype for an id such as `__proto__` to hit.
                const wakes: PendingWakeWrite['wakes'] = Object.create(null)
                for (const wait of hogflow.actions) {
                    if (wait.type !== 'wait_until_condition') {
                        continue
                    }
                    const key = `${hogflow.id}:${wait.id}:${candidate.teamId}:${candidate.distinctId ?? ''}:${candidate.personId ?? ''}`
                    let pending = waitWakes.get(key)
                    if (!pending) {
                        pending = evaluateWaitWake(
                            eventsOnly ? eventsOnlyWait(wait) : wait,
                            candidateGlobals,
                            filterGlobalsFor,
                            source,
                            hogflow.id
                        )
                        waitWakes.set(key, pending)
                    }
                    const wake = await pending
                    if (wake) {
                        wakes[wait.id] = wake
                    }
                }
                if (Object.keys(wakes).length > 0) {
                    pendingWakes.push({ id: candidate.id, wakes })
                }
                continue
            }

            const parkedOn = candidate.actionId
                ? hogflow.actions.find((a: HogFlowAction) => a.id === candidate.actionId)
                : undefined
            const action = eventsOnly && parkedOn?.type === 'wait_until_condition' ? eventsOnlyWait(parkedOn) : parkedOn

            // Any single matching event is enough. Stop early once both flags are set.
            let stepMatched = false
            let recheckMatched = false
            let stepMatchedEventName: string | undefined
            let stepMatchedEventUuid: string | undefined
            let stepMatchedEventTimestamp: string | undefined
            let conversionMatched = false
            let conversionDistinctId: string | undefined
            let conversionEventName: string | undefined
            let conversionEventUuid: string | undefined
            for (const globals of candidateGlobals) {
                const filterGlobals = filterGlobalsFor(globals)
                if (!stepMatched && !recheckMatched && action?.type === 'wait_until_condition') {
                    if (source === 'person' && conditionNeedsRunGlobals(action)) {
                        recheckMatched = true
                    } else if (
                        await matchesWaitUntilCondition(action, filterGlobals, {
                            hogFlowId: hogflow.id,
                            actionId: action.id,
                        })
                    ) {
                        stepMatched = true
                        parkedCheck.noteMatch(globals)
                        stepMatchedEventName = globals.event.event
                        stepMatchedEventUuid = globals.event.uuid
                        stepMatchedEventTimestamp = globals.event.timestamp
                    }
                }
                if (!conversionMatched && (await this.evaluateConversionEvents(hogflow, filterGlobals, eventsOnly))) {
                    conversionMatched = true
                    parkedCheck.noteMatch(globals)
                    // Remember who converted (and via which event) so we can emit $workflows_conversion.
                    conversionDistinctId = globals.event.distinct_id
                    conversionEventName = globals.event.event
                    conversionEventUuid = globals.event.uuid
                }
                if (stepMatched && conversionMatched) {
                    break
                }
            }

            // Collect a job when its wait step matched OR a conversion matched. Conversion matches are
            // collected even on measurement-only (non-exit) flows: processMatchedJobs reads the job's
            // state under FOR UPDATE to count the conversion exactly once per run (and surface it to
            // the executor for exit-on-conversion flows). The wake-vs-count-only decision is made there.
            if (stepMatched || recheckMatched || conversionMatched) {
                matchedJobs.push({
                    id: candidate.id,
                    actionId: candidate.actionId,
                    teamId: candidate.teamId,
                    functionId: candidate.functionId,
                    parentRunId: candidate.parentRunId,
                    stepMatched,
                    recheckMatched,
                    conversionMatched,
                    exitsOnConversion: exitsOnConversion(hogflow),
                    eventName: stepMatchedEventName,
                    eventUuid: stepMatchedEventUuid,
                    eventTimestamp: stepMatchedEventTimestamp,
                    conversionDistinctId,
                    conversionEventName,
                    conversionEventUuid,
                })
            }
        }

        if (matchedJobs.length > 0) {
            const { woken, inFlight } = await this.processMatchedJobs(matchedJobs)
            counterHogflowMatcherJobsWoken.inc(woken)
            logger.info('⚡', 'Processed waiting workflows from event match', {
                evaluated: candidates.length,
                matched: matchedJobs.length,
                woken,
            })
            // A worker took these jobs between the candidate read and the wake.
            for (const m of inFlight) {
                if (!m.actionId || !(m.stepMatched || m.recheckMatched)) {
                    continue
                }
                pendingWakes.push({
                    id: m.id,
                    wakes: {
                        [m.actionId]: m.stepMatched
                            ? {
                                  kind: 'match',
                                  eventName: m.eventName,
                                  eventUuid: m.eventUuid,
                                  eventTimestamp: m.eventTimestamp,
                              }
                            : { kind: 'recheck' },
                    },
                })
            }
        }

        if (pendingWakes.length > 0) {
            await this.recordPendingWakes(pendingWakes)
        }
    }

    // The worker's park write acts on these. A job released before this write is woken here instead.
    private async recordPendingWakes(writes: PendingWakeWrite[]): Promise<void> {
        const wakesById = new Map<string, PendingWakeWrite['wakes']>()
        for (const w of writes) {
            const merged: PendingWakeWrite['wakes'] = Object.assign(Object.create(null), wakesById.get(w.id))
            for (const [actionId, wake] of Object.entries(w.wakes)) {
                if (merged[actionId]?.kind !== 'match') {
                    merged[actionId] = wake
                }
            }
            wakesById.set(w.id, merged)
        }
        const ids = [...wakesById.keys()].sort()
        const client = await this.cyclotronPool.connect()
        try {
            await client.query('BEGIN')
            const locked = await client.query(
                `SELECT id, status, action_id, CASE WHEN status = 'available' THEN state END AS state, pending_wake, last_transition
                 FROM cyclotron_jobs WHERE id = ANY($1::uuid[]) AND status IN ('available', 'running')
                 ORDER BY id FOR UPDATE`,
                [ids]
            )
            const updateIds: string[] = []
            const updateWakes: string[] = []
            const updateWakeNow: boolean[] = []
            for (const row of locked.rows) {
                const existing = (row.pending_wake ?? {}) as Record<string, { kind: string; at: string }>
                const dequeuedAt = new Date(row.last_transition).getTime()
                const changed: PendingWakeWrite['wakes'] = Object.create(null)
                for (const [actionId, wake] of Object.entries(wakesById.get(row.id) ?? {})) {
                    const current = Object.hasOwn(existing, actionId) ? existing[actionId] : undefined
                    // A parked row keeps only entries its next dequeue has yet to apply.
                    const fresh =
                        current && (row.status === 'available' || new Date(current.at).getTime() >= dequeuedAt)
                    // A fresh match carries the event, which a later re-check of the same step would lose.
                    if (fresh && (current.kind === 'match' || wake.kind === 'recheck')) {
                        continue
                    }
                    changed[actionId] = wake
                }
                if (Object.keys(changed).length === 0) {
                    continue
                }
                updateIds.push(row.id)
                updateWakes.push(sanitizeJsonbValue(changed))
                updateWakeNow.push(
                    row.status === 'available' &&
                        Object.hasOwn(changed, row.action_id) &&
                        !decodeJobState(row).state?.currentAction?.cohortLookupAttempts
                )
            }
            const result = await client.query(
                `UPDATE cyclotron_jobs cj
                 SET pending_wake = COALESCE(cj.pending_wake, '{}'::jsonb) || (
                         SELECT jsonb_object_agg(w.key, w.value || jsonb_build_object('at', clock_timestamp()))
                         FROM jsonb_each(u.wakes) w
                     ),
                     scheduled = CASE WHEN u.wake_now THEN LEAST(cj.scheduled, NOW()) ELSE cj.scheduled END
                 FROM (SELECT unnest($1::uuid[]) AS id, unnest($2::jsonb[]) AS wakes, unnest($3::boolean[]) AS wake_now) u
                 WHERE cj.id = u.id`,
                [updateIds, updateWakes, updateWakeNow]
            )
            await client.query('COMMIT')
            counterHogflowMatcherPendingWakesRecorded.inc(result.rowCount ?? 0)
        } catch (err) {
            await client.query('ROLLBACK').catch(() => {})
            throw err
        } finally {
            client.release()
        }
    }

    // Splits the events into those to look up and those no filter of their team passes. In shadow mode it
    // looks up all of them anyway, and noteMatch counts a match on an event that "on" would have skipped.
    private async checkFilters(
        mode: FilterFirstMode,
        lookup: 'parked' | 'watchers' | 'watcher_goals',
        invocationGlobals: HogFunctionInvocationGlobals[],
        // `spent` turns true once the batch is over budget; `passes` then answers true without evaluating.
        passes: (globals: HogFunctionInvocationGlobals, spent: () => boolean) => boolean | Promise<boolean>
    ): Promise<{
        lookup: HogFunctionInvocationGlobals[]
        noteMatch: (globals: HogFunctionInvocationGlobals) => void
    }> {
        if (mode === 'off') {
            return { lookup: invocationGlobals, noteMatch: () => {} }
        }
        const failed = new Set<HogFunctionInvocationGlobals>()
        const startedAt = performance.now()
        const spent = (): boolean => performance.now() - startedAt > FILTER_FIRST_BUDGET_MS
        let unchecked = 0
        for (const globals of invocationGlobals) {
            if (!(await passes(globals, spent))) {
                failed.add(globals)
            } else if (spent()) {
                unchecked++
            }
        }
        counterHogflowMatcherFilterFirstEvents
            .labels({ lookup, result: 'pass' })
            .inc(invocationGlobals.length - failed.size - unchecked)
        counterHogflowMatcherFilterFirstEvents.labels({ lookup, result: 'fail' }).inc(failed.size)
        counterHogflowMatcherFilterFirstEvents.labels({ lookup, result: 'over_budget' }).inc(unchecked)
        return {
            lookup: mode === 'on' ? invocationGlobals.filter((globals) => !failed.has(globals)) : invocationGlobals,
            noteMatch: (globals) => {
                if (failed.has(globals)) {
                    counterHogflowMatcherFilterFirstMissed.labels({ lookup }).inc()
                }
            },
        }
    }

    // Whether the event could end a wait or meet a goal in any of the flows. A parked run is woken only
    // when its own wait step or its flow's goal matches, so an event that matches none of them cannot wake it.
    private async couldMoveRun(flows: HogFlow[], filterGlobals: FilterGlobals, spent: () => boolean): Promise<boolean> {
        for (const flow of flows) {
            if (spent() || flowCallsRandom(flow)) {
                return true
            }
            for (const action of flow.actions) {
                if (spent()) {
                    return true
                }
                if (
                    action.type === 'wait_until_condition' &&
                    (await matchesWaitUntilCondition(action, filterGlobals, {
                        hogFlowId: flow.id,
                        actionId: action.id,
                    }))
                ) {
                    return true
                }
            }
            if (spent() || (await this.evaluateConversionEvents(flow, filterGlobals, false))) {
                return true
            }
        }
        return false
    }

    private async evaluateConversionEvents(
        hogflow: HogFlow,
        filterGlobals: FilterGlobals,
        eventsOnly: boolean
    ): Promise<boolean> {
        const conversionEvents = hogflow.conversion?.events ?? []
        const context = { hogFlowId: hogflow.id }
        for (const eventConfig of conversionEvents) {
            if (!hasEventOrActionTarget(eventConfig)) {
                continue
            }
            if (eventsOnly && readsPerson(eventConfig.filters?.bytecode)) {
                continue
            }
            if (await runFilterBytecode(eventConfig.filters?.bytecode, filterGlobals, context)) {
                return true
            }
        }
        return false
    }

    private async findParkedJobs(
        distinctTeamIds: number[],
        distinctIds: string[],
        personTeamIds: number[],
        personIds: string[],
        functionIds: string[],
        source: WakeSource,
        earliestArrival: Date
    ): Promise<ParkedCandidate[]> {
        // Two index-friendly branches with UNION (dedupes rows that match both keys).
        // A single OR across distinct_id and person_id often forces Postgres into a
        // sequential scan; splitting lets each branch hit its own composite index.
        // Each branch correlates (team_id, id) as a tuple via `unnest(teams, ids)`, which
        // zips the parallel arrays row-wise — a job only matches when its team and its id
        // came from the SAME event. Filtering team_id and distinct_id independently with
        // ANY/ANY would match a job whose team and distinct_id came from two different
        // events in the batch (a cross-team false-positive candidate). The function_id
        // filter further scopes to flows the matcher can act on.
        //
        // We deliberately do NOT filter by queue_name: a parked wait can sit on a queue
        // other than 'hogflow'. When a step (e.g. email) routes the invocation to a
        // dedicated queue, the following wait parks on that queue, so a queue_name='hogflow'
        // filter would silently miss it. function_id already scopes to hogflow jobs, and
        // waking the job (scheduled = NOW()) lets whichever worker owns that queue resume it.
        const stopTimer = histogramHogflowMatcherFindParkedJobs.startTimer({ stream: source })
        let result
        try {
            result = await this.cyclotronPool.query(
                `SELECT id, team_id, function_id, parent_run_id, action_id, distinct_id, person_id, scheduled, status
             FROM cyclotron_jobs
             WHERE ((status = 'available' AND scheduled > $6) OR status = 'running')
               AND function_id = ANY($5::uuid[])
               AND (team_id, distinct_id) IN (SELECT * FROM unnest($1::int[], $2::text[]))
             UNION
             SELECT id, team_id, function_id, parent_run_id, action_id, distinct_id, person_id, scheduled, status
             FROM cyclotron_jobs
             WHERE ((status = 'available' AND scheduled > $6) OR status = 'running')
               AND function_id = ANY($5::uuid[])
               AND (team_id, person_id) IN (SELECT * FROM unnest($3::int[], $4::text[]))`,
                [distinctTeamIds, distinctIds, personTeamIds, personIds, functionIds, earliestArrival]
            )
        } finally {
            stopTimer()
        }

        return result.rows.map((row) => ({
            id: row.id,
            teamId: row.team_id,
            functionId: row.function_id,
            parentRunId: row.parent_run_id,
            actionId: row.action_id,
            distinctId: row.distinct_id,
            personId: row.person_id,
            // The hub's type parsers return timestamps as ISO strings, not dates.
            scheduledAt: new Date(row.scheduled).getTime(),
            status: row.status,
        }))
    }

    // Only ever resumes runs. Conversions are counted by claimConversionWatchers, which is what keeps
    // a conversion countable after the run it belongs to has finished.
    private async processMatchedJobs(matched: MatchedJob[]): Promise<{ woken: number; inFlight: MatchedJob[] }> {
        if (matched.length === 0) {
            return { woken: 0, inFlight: [] }
        }

        const ids = matched.map((m) => m.id)
        // The state read-modify-write must be atomic: two matcher instances acting on the same job
        // would otherwise both read the original state and the later UPDATE would drop the earlier
        // flag. SELECT ... FOR UPDATE inside a transaction serializes them. ORDER BY id keeps lock
        // acquisition order consistent across instances so concurrent batches can't deadlock.
        const client = await this.cyclotronPool.connect()
        try {
            await client.query('BEGIN')

            const stateRows = await client.query(
                `SELECT id, state FROM cyclotron_jobs
                 WHERE id = ANY($1::uuid[]) AND status = 'available'
                 ORDER BY id
                 FOR UPDATE`,
                [ids]
            )

            const matchedById = new Map(matched.map((m) => [m.id, m]))
            // Woken jobs get `scheduled = NOW()`; the rest get a state write that leaves `scheduled`
            // untouched, so a flag persists without pulling a parked job forward.
            const wakeUpdates: { id: string; state: Buffer }[] = []
            const stateOnlyUpdates: { id: string; state: Buffer }[] = []
            for (const row of stateRows.rows) {
                if (!row.state) {
                    continue
                }
                const m = matchedById.get(row.id)
                if (!m) {
                    continue
                }
                const outcome = applyMatchToState(row.state, m)
                if (!outcome) {
                    continue
                }
                if (outcome.wake) {
                    wakeUpdates.push({ id: row.id, state: outcome.state })
                } else {
                    stateOnlyUpdates.push({ id: row.id, state: outcome.state })
                }
            }

            let woken = 0
            if (wakeUpdates.length > 0) {
                const result = await client.query(
                    `UPDATE cyclotron_jobs cj
                     SET scheduled = NOW(), state = u.state
                     FROM (
                         SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state
                     ) u
                     WHERE cj.id = u.id AND cj.status = 'available'`,
                    [wakeUpdates.map((u) => u.id), wakeUpdates.map((u) => u.state)]
                )
                woken = result.rowCount ?? 0
            }
            if (stateOnlyUpdates.length > 0) {
                await client.query(
                    `UPDATE cyclotron_jobs cj
                     SET state = u.state
                     FROM (
                         SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state
                     ) u
                     WHERE cj.id = u.id AND cj.status = 'available'`,
                    [stateOnlyUpdates.map((u) => u.id), stateOnlyUpdates.map((u) => u.state)]
                )
            }
            await client.query('COMMIT')

            const parked = new Set(stateRows.rows.map((row) => row.id))
            return { woken, inFlight: matched.filter((m) => !parked.has(m.id)) }
        } catch (err) {
            await client.query('ROLLBACK').catch(() => {})
            throw err
        } finally {
            client.release()
        }
    }

    /**
     * Counts conversions by claiming the watcher rows of runs whose goal this batch satisfied.
     *
     * Runs against watchers rather than parked jobs, which is what lets a conversion count after the
     * run has ended — by then the run's cyclotron job is gone. Deleting the watcher IS the claim, so
     * two matcher instances racing on the same run cannot both count it, and no lock or state parse
     * is involved. Never touches cyclotron_jobs: exiting early on conversion is the run's business,
     * handled by processMatchedJobs.
     */
    private async claimConversionWatchers(
        indexed: IndexedBatch,
        filterGlobalsFor: (globals: HogFunctionInvocationGlobals) => FilterGlobals,
        eventsOnly: boolean,
        earliestArrival: Date,
        arrivedAt: (globals: HogFunctionInvocationGlobals) => Date,
        noteMatch: (globals: HogFunctionInvocationGlobals) => void = () => {}
    ): Promise<number> {
        const { distinctTeamIds, distinctIds, personTeamIds, personIds, byDistinctId, byPersonId } = indexed

        const stopTimer = histogramHogflowMatcherFindWatchers.startTimer()
        let found
        try {
            found = await this.cyclotronPool.query(
                `SELECT id, team_id, function_id, run_id, parent_run_id, distinct_id, person_id, flow_version, goal, created_at, expires_at
                 FROM conversion_watchers
                 WHERE expires_at > $5
                   AND (team_id, distinct_id) IN (SELECT * FROM unnest($1::int[], $2::text[]))
                 UNION
                 SELECT id, team_id, function_id, run_id, parent_run_id, distinct_id, person_id, flow_version, goal, created_at, expires_at
                 FROM conversion_watchers
                 WHERE expires_at > $5
                   AND (team_id, person_id) IN (SELECT * FROM unnest($3::int[], $4::text[]))`,
                [distinctTeamIds, distinctIds, personTeamIds, personIds, earliestArrival]
            )
        } finally {
            stopTimer()
        }
        if (found.rows.length === 0) {
            return 0
        }
        counterHogflowMatcherWatchersEvaluated.inc(found.rows.length)

        const converted: {
            row: any
            distinctId?: string
            conversionType: 'property' | 'event'
            eventName?: string
            eventUuid?: string
        }[] = []
        for (const row of found.rows) {
            // A watcher with no usable goal can never convert. Skipping it keeps a malformed row from
            // throwing out of the whole batch, which also carries the unrelated wake path.
            if (!row.goal || typeof row.goal !== 'object') {
                counterHogflowMatcherWatchersSkipped.inc()
                continue
            }
            const candidateGlobals = collectCandidateGlobals(
                { teamId: row.team_id, distinctId: row.distinct_id, personId: row.person_id },
                byDistinctId,
                byPersonId
            ).filter((globals) => arrivedAt(globals).getTime() < new Date(row.expires_at).getTime())
            const goal: PinnedConversionGoal = eventsOnly
                ? { events: row.goal.events?.filter((bytecode: unknown) => !readsPerson(bytecode)) }
                : row.goal
            for (const globals of candidateGlobals) {
                const conversionType = await matchesPinnedGoal(goal, filterGlobalsFor(globals), row.function_id)
                if (conversionType) {
                    noteMatch(globals)
                    converted.push({
                        row,
                        distinctId: globals.event.distinct_id || row.distinct_id || undefined,
                        conversionType,
                        // Only an event goal is caused by the event that matched. A property goal is
                        // detected against person state carried by whatever event delivered the update
                        // (often the synthetic $person_updated, or an unrelated event), so stamping that
                        // event would attribute the conversion to something that did not cause it.
                        eventName: conversionType === 'event' ? globals.event.event : undefined,
                        eventUuid: conversionType === 'event' ? globals.event.uuid : undefined,
                    })
                    break
                }
            }
        }
        if (converted.length === 0) {
            return 0
        }

        // The delete is the claim: only rows this statement actually removed are counted, so a
        // concurrent instance that removed the same row first counts it and we do not.
        const claimed = await this.cyclotronPool.query(
            `DELETE FROM conversion_watchers WHERE id = ANY($1::uuid[]) RETURNING id`,
            [converted.map((c) => c.row.id)]
        )
        const claimedIds = new Set(claimed.rows.map((r) => r.id))

        for (const { row, distinctId, conversionType, eventName, eventUuid } of converted) {
            if (!claimedIds.has(row.id)) {
                continue
            }
            const conversionMetric: MinimalAppMetric = {
                team_id: row.team_id,
                app_source_id: row.parent_run_id ?? row.function_id,
                instance_id: row.function_id,
                metric_kind: 'other',
                metric_name: 'conversion',
                count: 1,
                app_source_version:
                    row.flow_version !== null ? { id: row.function_id, version: row.flow_version } : undefined,
            }
            this.hogFunctionMonitoringService.queueAppMetric(conversionMetric, 'hog_flow')
            this.hogFunctionMonitoringService.queueAppMetric(
                {
                    ...conversionMetric,
                    metric_name: 'conversion_by_start',
                    timestamp: DateTime.fromJSDate(new Date(row.created_at)),
                },
                'hog_flow'
            )
            // Surfaced as a billable event too, so conversions can power insights and cohorts. The run
            // id is what joins it back to the enrollment that earned it.
            //
            // A person-triggered run (batch audience, manual person trigger) enrolls with no
            // distinct_id, and a person-property change carries none either, so there is nothing to
            // attribute a capture event to. The app metric still counts, but any consumer reading
            // conversions from the event stream will not see these — watch the counter.
            if (!distinctId) {
                counterHogflowMatcherConversionEventSkipped.inc()
            }
            if (distinctId) {
                await this.invocationResultsService.capturedEventsService.queueEvent({
                    team_id: row.team_id,
                    event: '$workflows_conversion',
                    distinct_id: distinctId,
                    timestamp: new Date().toISOString(),
                    properties: {
                        $workflow_id: row.function_id,
                        $workflow_run_id: row.run_id,
                        $workflow_version: row.flow_version ?? undefined,
                        $workflow_conversion_type: conversionType,
                        $workflow_conversion_event: eventName,
                        $workflow_conversion_event_uuid: eventUuid,
                    },
                })
            }
        }
        return claimedIds.size
    }

    /**
     * Whether a team's messages are worth the full parse. True when it has a flow the matcher can act
     * on, or when it still has live conversion watchers.
     *
     * The watcher half matters because the flow cache is active-only. Pausing or archiving a team's
     * only goal workflow, or removing its goal, would otherwise drop every message for that team, and
     * its already-enrolled watchers would expire uncounted — silently under-reporting, and defeating
     * the point of pinning the goal to the run in the first place.
     */
    private async teamIsActionable(teamId: number): Promise<boolean> {
        const teamHogFlows = await this.hogFlowManager.getHogFlowsForTeam(teamId)
        if (teamHogFlows.some(hasWaitUntilOrConversion)) {
            return true
        }
        return this.mayHaveLiveWatchers(teamId)
    }

    private mayHaveLiveWatchers(teamId: number): boolean {
        if (this.usingPinnedGoals) {
            return (
                this.pinnedGoalsByTeam.has(teamId) ||
                this.teamsOverGoalCap.has(teamId) ||
                this.pinnedGoalChanges.has(teamId)
            )
        }
        return this.liveWatcherFlowsByTeam.has(teamId) || this.teamsWithChangedFlows.has(teamId)
    }

    // Every goal a watcher of the team can hold: each goal its workflows have had live, plus the current goals of
    // its cached flows. 'any' while the goals may be missing one: shortly after a flow change, or when the last
    // read is too old.
    private pinnedGoalsForTeam(teamId: number, flows: HogFlow[]): PinnedGoalEntry[] | 'any' {
        if (!this.pinnedGoalsFresh() || this.pinnedGoalChanges.has(teamId)) {
            return 'any'
        }
        if (this.teamsOverGoalCap.has(teamId)) {
            return 'any'
        }
        const stored = this.pinnedGoalsByTeam.get(teamId)
        const entries = [...(stored?.values() ?? [])]
        for (const flow of flows.filter(hasConversionGoal)) {
            const entry = currentGoalEntry(flow)
            if (entry && !stored?.has(entry.key)) {
                entries.push(entry)
            }
        }
        return entries
    }

    private pinnedGoalsFresh(): boolean {
        return Date.now() - this.pinnedGoalsReadAt < PINNED_GOALS_MAX_READ_AGE_MS
    }

    // Reads every goal live within the longest conversion window, so older goals and deleted workflows drop out.
    private async refreshPinnedGoals(): Promise<void> {
        const startedAt = Date.now()
        const windowStart = startedAt - MAX_CONVERSION_WINDOW_MINUTES * 60_000 - PINNED_GOALS_WINDOW_MARGIN_MS
        const goalsRead = {
            // One row past the cap is enough to know a team is over it, so one team cannot add more rows than that.
            text: `/* nodejs:hogflowMatcherPinnedGoals */ SELECT team_id, hog_flow_id, goal, event_names FROM (
                 SELECT team_id, hog_flow_id, goal, event_names,
                        row_number() OVER (PARTITION BY team_id ORDER BY last_live_at DESC) AS team_row
                 FROM workflows_hogflowconversiongoal
                 WHERE last_live_at > $1
             ) goals
             WHERE team_row <= $2`,
            query_timeout: PINNED_GOALS_READ_TIMEOUT_MS,
        }
        const result = await this.postgres.query<{
            team_id: number
            hog_flow_id: string
            goal: PinnedConversionGoal
            event_names: string[] | null
        }>(
            PostgresUse.COMMON_READ,
            goalsRead,
            [new Date(windowStart), PINNED_GOALS_MAX_PER_TEAM + 1],
            'hogflowMatcherPinnedGoals'
        )
        const pinnedGoalsByTeam = new Map<number, Map<string, PinnedGoalEntry>>()
        const rowsPerTeam = new Map<number, number>()
        for (const row of result.rows) {
            rowsPerTeam.set(row.team_id, (rowsPerTeam.get(row.team_id) ?? 0) + 1)
            if (!row.goal || typeof row.goal !== 'object') {
                continue
            }
            const entry: PinnedGoalEntry = {
                functionId: row.hog_flow_id,
                goal: row.goal,
                key: stableStringify(row.goal),
                eventNames: Array.isArray(row.event_names) ? new Set(row.event_names) : null,
            }
            let entries = pinnedGoalsByTeam.get(row.team_id)
            if (!entries) {
                entries = new Map()
                pinnedGoalsByTeam.set(row.team_id, entries)
            }
            const existing = entries.get(entry.key)
            // Equal goals keep the version that matches any event name.
            if (!existing || (existing.eventNames && entry.eventNames === null)) {
                entries.set(entry.key, entry)
            }
        }
        // A team over the cap looks up every event, so its goals are not kept.
        const teamsOverGoalCap = new Set<number>()
        for (const [teamId, count] of rowsPerTeam) {
            if (count > PINNED_GOALS_MAX_PER_TEAM) {
                teamsOverGoalCap.add(teamId)
                pinnedGoalsByTeam.delete(teamId)
            }
        }
        this.pinnedGoalsByTeam = pinnedGoalsByTeam
        this.teamsOverGoalCap = teamsOverGoalCap
        this.pinnedGoalsReadAt = startedAt
        for (const [teamId, changedAt] of this.pinnedGoalChanges) {
            if (startedAt - changedAt > PINNED_GOALS_CHANGE_WINDOW_MS) {
                this.pinnedGoalChanges.delete(teamId)
            }
        }
    }

    // One tick of the watcher state. The goals are read every tick while they are on or in shadow. The full watcher
    // scan stops once "on" has read the goals, and otherwise runs at most every WATCHER_TEAMS_REFRESH_INTERVAL_MS.
    private async refreshWatcherState(): Promise<void> {
        if (this.pinnedGoalsMode !== 'off') {
            if (!this.pinnedGoalsRead) {
                this.pinnedGoalsRead = this.refreshPinnedGoals()
                    .catch((err) => {
                        logger.error('⚠️', 'Failed to read conversion goals', { err })
                        captureException(err)
                    })
                    .finally(() => {
                        this.pinnedGoalsRead = null
                    })
            }
            // The query timeout does not cover the wait for a connection, which must not hold up start().
            let timer: NodeJS.Timeout | undefined
            await Promise.race([
                this.pinnedGoalsRead,
                new Promise<void>((resolve) => {
                    timer = setTimeout(resolve, PINNED_GOALS_READ_TIMEOUT_MS)
                    timer.unref?.()
                }),
            ])
            clearTimeout(timer)
        }
        this.usingPinnedGoals = this.pinnedGoalsMode === 'on' && this.pinnedGoalsReadAt > 0
        gaugeHogflowMatcherPinnedGoalsInUse.set(this.usingPinnedGoals && this.pinnedGoalsFresh() ? 1 : 0)
        if (this.usingPinnedGoals) {
            this.teamsWithChangedFlows.clear()
            gaugeHogflowMatcherTeamsWithWatchers.set(0)
        } else if (Date.now() - this.watcherRefreshedAt >= WATCHER_TEAMS_REFRESH_INTERVAL_MS) {
            // The cyclotron pool has no query timeout either, so a slow scan must not start another every tick.
            if (!this.watcherScan) {
                this.watcherScan = this.refreshTeamsWithLiveWatchers().finally(() => {
                    this.watcherScan = null
                })
            }
            await this.watcherScan
        }
    }

    // The flows whose current goals cover every goal the team's live watchers pinned, or 'any' when a
    // watcher may hold a goal that no cached flow still shows: a paused flow, or one edited since.
    private goalFlowsForWatchers(teamId: number, flows: HogFlow[]): HogFlow[] | 'any' {
        if (this.teamsWithChangedFlows.has(teamId)) {
            return 'any'
        }
        for (const [functionId, oldestCreatedAt] of this.liveWatcherFlowsByTeam.get(teamId) ?? []) {
            const flow = flows.find((f) => f.id === functionId)
            const updatedAt = flow ? toMillis(flow.updated_at) : null
            if (updatedAt === null || oldestCreatedAt <= updatedAt + PINNED_GOAL_CACHE_LAG_MS) {
                return 'any'
            }
        }
        return flows.filter(hasConversionGoal)
    }

    // One small query per refresh, returning at most one row per team that has ever enrolled a run on
    // a goal workflow. Kept as a whole-set replace so a team whose watchers have all expired drops out
    // without needing its own invalidation.
    private async refreshTeamsWithLiveWatchers(): Promise<void> {
        const refreshNumber = ++this.watcherRefreshNumber
        const result = await this.cyclotronPool.query(
            `SELECT team_id, function_id, MIN(created_at) AS oldest_created_at
             FROM conversion_watchers
             WHERE expires_at > NOW()
             GROUP BY team_id, function_id`
        )
        const liveWatcherFlowsByTeam = new Map<number, Map<string, number>>()
        for (const row of result.rows) {
            let flows = liveWatcherFlowsByTeam.get(row.team_id)
            if (!flows) {
                flows = new Map()
                liveWatcherFlowsByTeam.set(row.team_id, flows)
            }
            flows.set(row.function_id, new Date(row.oldest_created_at).getTime())
        }
        this.liveWatcherFlowsByTeam = liveWatcherFlowsByTeam
        for (const [teamId, change] of this.teamsWithChangedFlows) {
            if (change.refreshNumber < refreshNumber && Date.now() - change.at > PINNED_GOAL_CACHE_LAG_MS) {
                this.teamsWithChangedFlows.delete(teamId)
            }
        }
        this.watcherRefreshedAt = Date.now()
        gaugeHogflowMatcherTeamsWithWatchers.set(this.liveWatcherFlowsByTeam.size)
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const buildGlobals = (team: Team, clickHouseEvent: RawClickHouseEvent): HogFunctionInvocationGlobals =>
            convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.config.SITE_URL)
        return await this.parseMatcherBatch(messages, 'Error parsing message', (message) => {
            const headerTeamId = readTeamIdHeader(message)
            if (headerTeamId !== null) {
                counterTeamIdSource.labels({ source: 'header' }).inc()
                // The body stays unparsed until `toGlobals` runs, and it only runs for a team with an
                // actionable flow or live watchers. Most events belong to a team with neither.
                return {
                    teamId: headerTeamId,
                    toGlobals: (team) => {
                        const clickHouseEvent = parseEvent(message)
                        if (clickHouseEvent.team_id !== headerTeamId) {
                            // The team loads from the header and the event comes from the body, so a
                            // disagreement would let one team's event wake another team's parked runs.
                            counterTeamIdHeaderMismatch.inc()
                            throw new Error('team_id_header_mismatch')
                        }
                        return isMatchableEvent(clickHouseEvent) ? buildGlobals(team, clickHouseEvent) : null
                    },
                }
            }

            counterTeamIdSource.labels({ source: 'body' }).inc()
            const clickHouseEvent = parseEvent(message)
            if (!isMatchableEvent(clickHouseEvent)) {
                return null
            }
            return { teamId: clickHouseEvent.team_id, toGlobals: (team) => buildGlobals(team, clickHouseEvent) }
        })
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parseCohortMembershipMessages')
    public async _parseCohortMembershipBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.parseMatcherBatch(messages, 'Error parsing cohort membership change', (message) => {
            const parsed = parseJSON(message.value!.toString())
            if (isCohortMembershipControlRecord(parsed)) {
                return null
            }
            const change = CohortMembershipChangeSchema.parse(parsed)
            // Seed and reconcile changes restate membership the person already had. They are not a join
            // or a leave, so they must not satisfy a wait or a conversion goal.
            if (change.origin) {
                counterHogflowMatcherEventSkipped.labels({ reason: 'cohort_membership_backfill' }).inc()
                return null
            }
            return {
                teamId: change.team_id,
                toGlobals: (team) => convertCohortMembershipChangeToGlobals(change, team, this.config.SITE_URL),
            }
        })
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parsePersonMessages')
    public async _parsePersonBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.parseMatcherBatch(messages, 'Error parsing person message', (message) => {
            const data = parseJSON(message.value!.toString()) as ClickHousePerson
            // A deleted person can never satisfy a wait, so skip tombstones.
            if (data.is_deleted) {
                return null
            }
            // Parked waits are matched by person_id (the job's person.id), so a person
            // mutation needs an id to wake anything.
            if (!data.id) {
                counterHogflowMatcherEventSkipped.labels({ reason: 'no_identifiers' }).inc()
                return null
            }
            return {
                teamId: data.team_id,
                toGlobals: (team) => convertClickhousePersonToWakeGlobals(data, team, this.config.SITE_URL),
            }
        })
    }

    private async parseMatcherBatch(
        messages: Message[],
        errorLog: string,
        parse: ParseBatchOptions['parse']
    ): Promise<HogFunctionInvocationGlobals[]> {
        // A batch carries many messages per team, so each team is looked up once and the skips are counted once.
        const teams = new Map<number, Promise<Team | 'no_actionable_flow' | 'no_team'>>()
        const skipped = { no_actionable_flow: 0, no_team: 0 }
        const lookUp = async (teamId: number): Promise<Team | 'no_actionable_flow' | 'no_team'> => {
            // The vast majority of messages belong to teams with no wait_until_condition step and
            // no conversion goal. Bail on those via the in-memory hogflow cache before paying for
            // getTeam + full globals conversion.
            if (!(await this.teamIsActionable(teamId))) {
                return 'no_actionable_flow'
            }
            return (await this.deps.teamManager.getTeam(teamId)) ?? 'no_team'
        }
        try {
            return await parseBatch(messages, {
                errorLog,
                parse,
                onInvalidTeamId: () => counterHogflowMatcherEventSkipped.labels({ reason: 'invalid_team_id' }).inc(),
                // Do not catch a lookup error here. A skipped event leaves the wait or conversion goal that it
                // should satisfy to time out.
                loadTeam: async (teamId) => {
                    let team = teams.get(teamId)
                    if (!team) {
                        team = lookUp(teamId)
                        teams.set(teamId, team)
                    }
                    const result = await team
                    if (typeof result === 'string') {
                        skipped[result]++
                        return null
                    }
                    return result
                },
            })
        } finally {
            for (const [reason, count] of Object.entries(skipped)) {
                if (count > 0) {
                    counterHogflowMatcherEventSkipped.labels({ reason }).inc(count)
                }
            }
        }
    }

    // Step resumes name their job, so they skip the person and team gates the event parser applies.
    public _splitStepResumes(messages: Message[]): { resumes: StepResume[]; rest: Message[] } {
        const resumes: StepResume[] = []
        const rest: Message[] = []
        for (const message of messages) {
            let parsed
            try {
                parsed = CdpInternalEventSchema.parse(parseJSON(message.value!.toString()))
            } catch {
                rest.push(message)
                continue
            }
            if (parsed.event.event !== WORKFLOW_STEP_RESUME_EVENT) {
                rest.push(message)
                continue
            }
            const props = WorkflowStepResumeSchema.safeParse(parsed.event.properties)
            const key = props.success ? parseWorkflowStepDispatchKey(props.data.origin_key) : null
            if (!props.success || !key) {
                counterStepResume.labels({ outcome: 'parse_error' }).inc()
                continue
            }
            resumes.push({ ...props.data, ...key })
        }
        return { resumes, rest }
    }

    @instrumented('cdpHogflowSubscriptionMatcher.processStepResumes')
    public async processStepResumes(resumes: StepResume[]): Promise<void> {
        await processStepResumes(this.cyclotronPool, resumes)
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parseInternalEventMessages')
    public async _parseInternalEventsBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.parseMatcherBatch(messages, 'Error parsing internal event message', (message) => {
            const parsed = CdpInternalEventSchema.parse(parseJSON(message.value!.toString()))
            if (!parsed.event.distinct_id && !parsed.person?.id) {
                counterHogflowMatcherEventSkipped.labels({ reason: 'no_identifiers' }).inc()
                return null
            }
            return {
                teamId: parsed.team_id,
                toGlobals: (team) =>
                    convertInternalEventToHogFunctionInvocationGlobals(parsed, team, this.config.SITE_URL),
            }
        })
    }

    // Synchronous (no getTeam/globals conversion — a repoint only carries ids), so unlike the other
    // parsers this isn't async or @instrumented.
    public _parsePersonDistinctIdBatch(messages: Message[]): PersonDistinctIdMove[] {
        const moves: PersonDistinctIdMove[] = []
        for (const message of messages) {
            const move = skipIfMalformed(
                'Error parsing person distinct id message',
                (): PersonDistinctIdMove | null => {
                    const data = parseJSON(message.value!.toString()) as ClickHousePersonDistinctId2
                    // version > 0 is a repoint (identify/merge). version 0 is the distinct_id's first mapping
                    // to a person, which a wait parked before the person resolved needs to acquire its anchor:
                    // person wakes are keyed on person_id alone, so a job left with a null anchor is
                    // unwakeable by any person-property change. processMoveBatch scopes version 0 to exactly
                    // those jobs, which is what keeps this off the insert firehose.
                    if (data.version === undefined || data.version === null || data.version < 0) {
                        return null
                    }
                    // A distinct_id being deleted can't wake anything, and must never re-point a wait at a
                    // person that is going away.
                    if (data.is_deleted) {
                        return null
                    }
                    if (!data.distinct_id || !data.person_id) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_identifiers' }).inc()
                        return null
                    }
                    if (!isValidTeamId(data.team_id)) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'invalid_team_id' }).inc()
                        return null
                    }
                    return {
                        teamId: data.team_id,
                        distinctId: data.distinct_id,
                        newPersonId: data.person_id,
                        version: data.version,
                    }
                }
            )
            if (move) {
                moves.push(move)
            }
        }
        return moves
    }

    // Point parked wait_until_condition jobs at the person their distinct_id now belongs to, for the two
    // ways that can change: a merge repointing it onto a survivor, or the distinct_id acquiring a person
    // for the first time. Either way the job's existing anchor can no longer be woken — person and event
    // wakes are keyed on person_id — so we rewrite the anchor (column + state.personId) and wake it.
    public async processMoveBatch(moves: PersonDistinctIdMove[]): Promise<void> {
        if (moves.length === 0) {
            return
        }

        // A repoint (version > 0) may rewrite any parked wait's anchor. A first mapping (version 0) may
        // only fill an anchor that is missing: it says "this distinct_id now has a person", which tells us
        // nothing about a job already anchored elsewhere, and the null-anchor scope is what keeps the
        // insert firehose off the whole flow set.
        const repoints = moves.filter((m) => m.version > 0)
        const firstMappings = moves.filter((m) => m.version === 0)

        if (repoints.length > 0) {
            await this.applyMoves(repoints, false)
        }
        // Watchers are keyed the same two ways parked jobs are, so a merge that repoints a distinct_id
        // leaves the watcher addressed to a person nothing will ever update again. A watcher can live
        // for the whole attribution window, so it is far more likely than a parked job to outlast a
        // merge, and an unreachable one silently stops counting.
        await this.rekeyWatchers(moves)
        if (firstMappings.length > 0) {
            counterHogflowMatcherFirstMapping.labels({ outcome: 'seen' }).inc(firstMappings.length)
            await this.applyMoves(firstMappings, true)
        }
    }

    private async rekeyWatchers(moves: PersonDistinctIdMove[]): Promise<void> {
        // Highest version wins per distinct_id: repoints are not Kafka-keyed, so a batch can carry a
        // chain (anon -> A -> B) out of order, and re-keying onto an intermediate person would leave
        // the watcher just as unreachable.
        const survivorByKey = new Map<string, { personId: string; version: number }>()
        for (const move of moves) {
            const key = `${move.teamId}:${move.distinctId}`
            const existing = survivorByKey.get(key)
            if (!existing || move.version > existing.version) {
                survivorByKey.set(key, { personId: move.newPersonId, version: move.version })
            }
        }
        const teamIds: number[] = []
        const distinctIds: string[] = []
        const personIds: string[] = []
        const versions: number[] = []
        for (const [key, survivor] of survivorByKey) {
            const [teamId, ...distinctIdParts] = key.split(':')
            teamIds.push(Number(teamId))
            distinctIds.push(distinctIdParts.join(':'))
            personIds.push(survivor.personId)
            versions.push(survivor.version)
        }

        // Let a re-key failure propagate, like applyMoves and the read/wake path do: it fails the batch
        // so the offset doesn't advance and the pod replays. The UPDATE is idempotent — a no-op once
        // person_id already matches — so replay is safe. Swallowing it here instead would strand every
        // watcher in the batch on its pre-merge person until it expires, silently under-counting.
        const result = await this.cyclotronPool.query(
            `UPDATE conversion_watchers w
             SET person_id = u.person_id, person_version = u.version
             FROM (
                 SELECT unnest($1::int[]) AS team_id, unnest($2::text[]) AS distinct_id, unnest($3::text[]) AS person_id, unnest($4::int[]) AS version
             ) u
             WHERE w.team_id = u.team_id AND w.distinct_id = u.distinct_id AND w.person_id IS DISTINCT FROM u.person_id
               -- Ordering within a batch is handled above; this is the cross-batch half. A repoint that
               -- arrives after a higher-versioned one would otherwise rewind the anchor to an
               -- intermediate person, leaving the watcher unreachable by person_id until it expires.
               AND u.version > w.person_version
               -- A first mapping (version 0) only says "this distinct_id now has a person"; it may fill
               -- an empty anchor but must not overwrite one a merge already set, mirroring the
               -- onlyNullAnchor scope applyMoves uses. Repoints (version > 0) may repoint any anchor.
               AND (u.version > 0 OR w.person_id IS NULL)`,
            [teamIds, distinctIds, personIds, versions]
        )
        counterHogflowMatcherWatchersRekeyed.inc(result.rowCount ?? 0)
    }

    private async applyMoves(moves: PersonDistinctIdMove[], onlyNullAnchor: boolean): Promise<void> {
        // Only flows with a wait_until_condition step can have a parked wait to re-key. Scope the
        // function_id filter to them so the cyclotron query stays index-friendly and skips repoints for
        // teams with no such flow.
        const teamIds = [...new Set(moves.map((m) => m.teamId))]
        const hogFlowsByTeam = await this.hogFlowManager.getHogFlowsForTeams(teamIds)
        const hogflows: Record<string, HogFlow> = {}
        for (const flows of Object.values(hogFlowsByTeam)) {
            for (const flow of flows) {
                if (flow.actions.some((a: HogFlowAction) => a.type === 'wait_until_condition')) {
                    hogflows[flow.id] = flow
                }
            }
        }
        const functionIds = Object.keys(hogflows)
        if (functionIds.length === 0) {
            return
        }

        // A batch can carry several repoints for the same distinct_id (chained merges anon → A → B).
        // Repoints aren't Kafka-keyed, so they may arrive out of order within the batch — keep the
        // highest-version survivor per key rather than the last array entry, or we could re-key onto an
        // intermediate person the survivor's person-stream updates would never wake.
        const newPersonByKey = new Map<string, { personId: string; version: number }>()
        for (const move of moves) {
            const key = `${move.teamId}:${move.distinctId}`
            const existing = newPersonByKey.get(key)
            if (!existing || move.version > existing.version) {
                newPersonByKey.set(key, { personId: move.newPersonId, version: move.version })
            }
        }
        const moveTeamIds = moves.map((m) => m.teamId)
        const moveDistinctIds = moves.map((m) => m.distinctId)

        // Scope the lock + state fetch to the wait_until_condition steps we can actually re-key, so jobs
        // of the same flow parked on unrelated steps (e.g. a delay) aren't locked or shipped over the wire.
        const waitActionIds = Object.values(hogflows).flatMap((flow) =>
            flow.actions.filter((a: HogFlowAction) => a.type === 'wait_until_condition').map((a) => a.id)
        )

        let updatedCount = 0
        const pendingWakes: PendingWakeWrite[] = []
        const client = await this.cyclotronPool.connect()
        try {
            await client.query('BEGIN')
            // Lock the parked jobs for the repointed distinct_ids. ORDER BY id keeps lock order consistent
            // with processMatchedJobs so concurrent move/match batches can't deadlock.
            // A running job's state is rewritten on release, so it gets a re-check instead of a re-key.
            const rows = await client.query(
                `SELECT id, team_id, distinct_id, function_id, action_id, state, status
                 FROM cyclotron_jobs
                 WHERE function_id = ANY($3::uuid[])
                   AND (team_id, distinct_id) IN (SELECT * FROM unnest($1::int[], $2::text[]))
                   AND (status = 'running' OR (
                       status = 'available'
                       AND action_id = ANY($4::text[])
                       ${onlyNullAnchor ? 'AND person_id IS NULL' : ''}
                   ))
                 ORDER BY id
                 FOR UPDATE`,
                [moveTeamIds, moveDistinctIds, functionIds, waitActionIds]
            )

            const updates: { id: string; personId: string; state: Buffer }[] = []
            for (const row of rows.rows) {
                if (row.status === 'running') {
                    const waits = hogflows[row.function_id].actions.filter(
                        (a: HogFlowAction) => a.type === 'wait_until_condition'
                    )
                    pendingWakes.push({
                        id: row.id,
                        wakes: Object.fromEntries(waits.map((a) => [a.id, { kind: 'recheck' as const }])),
                    })
                    continue
                }
                // Only re-key jobs currently parked ON a wait_until_condition step. A job of the same flow
                // could be parked in a delay; rewriting its person_id off a repoint would be wrong, and it
                // must never be pulled forward.
                const action = row.action_id
                    ? hogflows[row.function_id]?.actions.find((a: HogFlowAction) => a.id === row.action_id)
                    : undefined
                if (action?.type !== 'wait_until_condition') {
                    continue
                }
                const newPerson = newPersonByKey.get(`${row.team_id}:${row.distinct_id}`)
                if (!newPerson || !row.state) {
                    continue
                }
                const newState = rewriteStatePersonId(
                    row.state,
                    newPerson.personId,
                    newPerson.version,
                    row.id,
                    onlyNullAnchor
                )
                if (!newState) {
                    continue
                }
                updates.push({ id: row.id, personId: newPerson.personId, state: newState })
            }

            if (updates.length > 0) {
                // scheduled = NOW() wakes the parked wait on the repoint itself, closing the ordering
                // race where the person-property update lands before this re-key (the matcher would
                // otherwise miss the still-anon-keyed job and the wait would hang until its poll tick).
                // Safe now that the worker resolves a re-keyed job by survivor personId (personIdRepointed).
                const result = await client.query(
                    `UPDATE cyclotron_jobs cj
                     SET person_id = u.person_id, state = u.state, scheduled = NOW()
                     FROM (
                         SELECT unnest($1::uuid[]) AS id, unnest($2::text[]) AS person_id, unnest($3::bytea[]) AS state
                     ) u
                     WHERE cj.id = u.id AND cj.status = 'available'`,
                    [updates.map((u) => u.id), updates.map((u) => u.personId), updates.map((u) => u.state)]
                )
                updatedCount = result.rowCount ?? 0
            }
            await client.query('COMMIT')
            // Counted after COMMIT: an UPDATE that succeeds and then fails to commit is rolled back, so
            // counting before this would report anchors that no job actually carries.
            if (updatedCount > 0) {
                if (onlyNullAnchor) {
                    counterHogflowMatcherFirstMapping.labels({ outcome: 'filled' }).inc(updatedCount)
                } else {
                    counterHogflowMatcherJobsRekeyedOnMove.inc(updatedCount)
                }
            }
        } catch (err) {
            await client.query('ROLLBACK').catch(() => {})
            throw err
        } finally {
            client.release()
        }
        if (pendingWakes.length > 0) {
            await this.recordPendingWakes(pendingWakes)
        }
    }

    public override async start(): Promise<void> {
        await super.start()
        // Awaited so the first batches are gated against a populated set rather than an empty one,
        // which would drop messages for teams whose only goal flow is paused. A failure here must not
        // stop the matcher starting: an empty set degrades the gate to its previous flow-only
        // behavior until a retry succeeds, which is milder than refusing to consume at all.
        await this.refreshWatcherState().catch((err) => {
            logger.error('⚠️', 'Initial conversion-watcher team refresh failed; gating on flows alone', { err })
            captureException(err)
        })
        this.watcherTeamsRefreshTimer = setInterval(() => {
            void this.refreshWatcherState().catch((err) => {
                logger.error('⚠️', 'Failed to refresh teams with live conversion watchers', { err })
                captureException(err)
            })
        }, WATCHER_TEAMS_REFRESH_RETRY_MS)
        // Not work the process should stay alive for: periodic maintenance that the next start picks
        // up. Unref'd, a consumer that was started but never stopped cannot hold the event loop open —
        // which is what a leaked one does to a long single-process test run.
        this.watcherTeamsRefreshTimer.unref()
        // Surface failures to each kafka consumer so the offset doesn't advance past a batch we
        // couldn't match. The pod will crash and replay; the SELECT is read-only and the UPDATE
        // (with `status = 'available'` guards) is idempotent, so replay is safe. All the streams
        // funnel into the same input-agnostic wakeMatchingWorkflows via processBatch.
        await Promise.all([
            this.kafkaConsumer.connect(this.eventsBatchHandler('cdpHogflowSubscriptionMatcher.handleEachBatch')),
            this.personKafkaConsumer.connect(async (messages) => {
                return await instrumentFn('cdpHogflowSubscriptionMatcher.handlePersonBatch', async () => {
                    return { backgroundTask: this.processBatch(await this._parsePersonBatch(messages), 'person') }
                })
            }),
            this.internalEventsKafkaConsumer.connect(async (messages) => {
                return await instrumentFn('cdpHogflowSubscriptionMatcher.handleInternalEventsBatch', async () => {
                    const { resumes, rest } = this._splitStepResumes(messages)
                    const events = await this._parseInternalEventsBatch(rest)
                    return {
                        backgroundTask: Promise.all([
                            this.processBatch(events, 'internal_events'),
                            this.processStepResumes(resumes),
                        ]).then(() => undefined),
                    }
                })
            }),
            this.personDistinctIdKafkaConsumer.connect(async (messages) => {
                // Parsing repoints is synchronous, so wrap in a resolved promise to satisfy instrumentFn's
                // promise-returning callback without a no-op async body.
                return await instrumentFn('cdpHogflowSubscriptionMatcher.handlePersonDistinctIdBatch', () =>
                    Promise.resolve({
                        backgroundTask: this.processMoveBatch(this._parsePersonDistinctIdBatch(messages)),
                    })
                )
            }),
            this.realtimeOnlyEventsKafkaConsumer?.connect(
                this.eventsBatchHandler('cdpHogflowSubscriptionMatcher.handleRealtimeOnlyEventsBatch')
            ),
            this.cohortMembershipKafkaConsumer.connect(async (messages) => {
                return await instrumentFn('cdpHogflowSubscriptionMatcher.handleCohortMembershipBatch', async () => ({
                    backgroundTask: this.processBatch(
                        await this._parseCohortMembershipBatch(messages),
                        'cohort_membership'
                    ),
                }))
            }),
        ])
    }

    private eventsBatchHandler(
        instrumentKey: string
    ): (messages: Message[]) => Promise<{ backgroundTask: Promise<void> }> {
        return async (messages) =>
            await instrumentFn(instrumentKey, async () => ({
                backgroundTask: this.eventWakes.add(this.stampArrival(await this._parseKafkaBatch(messages))),
            }))
    }

    private stampArrival(invocationGlobals: HogFunctionInvocationGlobals[]): HogFunctionInvocationGlobals[] {
        const arrivedAt = new Date(Date.now())
        for (const globals of invocationGlobals) {
            this.eventArrivals.set(globals, arrivedAt)
        }
        return invocationGlobals
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        if (this.watcherTeamsRefreshTimer) {
            clearInterval(this.watcherTeamsRefreshTimer)
        }
        // The consumers wait for their batches' background tasks before committing on disconnect.
        this.eventWakes.flush()
        await Promise.all([
            this.kafkaConsumer.disconnect(),
            this.personKafkaConsumer.disconnect(),
            this.internalEventsKafkaConsumer.disconnect(),
            this.personDistinctIdKafkaConsumer.disconnect(),
            this.realtimeOnlyEventsKafkaConsumer?.disconnect(),
            this.cohortMembershipKafkaConsumer.disconnect(),
        ])
        await this.cyclotronPool.end()
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        // Unhealthy if any stream is unhealthy: with polling gone, a stalled stream means dropped wakes.
        const results = [
            this.kafkaConsumer.isHealthy(),
            this.personKafkaConsumer.isHealthy(),
            this.internalEventsKafkaConsumer.isHealthy(),
            this.personDistinctIdKafkaConsumer.isHealthy(),
            ...(this.realtimeOnlyEventsKafkaConsumer ? [this.realtimeOnlyEventsKafkaConsumer.isHealthy()] : []),
            this.cohortMembershipKafkaConsumer.isHealthy(),
        ]
        return results.find((r) => r.status !== 'ok') ?? results[0]
    }
}

function parseEvent(message: Message): RawClickHouseEvent {
    return parseJSON(message.value!.toString()) as RawClickHouseEvent
}

function isMatchableEvent(clickHouseEvent: RawClickHouseEvent): boolean {
    // A job can be parked by distinct_id or person_id, so an event needs at least
    // one of them to match anything. Drop only events that carry neither.
    if (!clickHouseEvent.person_id && !clickHouseEvent.distinct_id) {
        counterHogflowMatcherEventSkipped.labels({ reason: 'no_identifiers' }).inc()
        return false
    }
    // Only the cohort membership topic says who joined or left a cohort. Anyone with the
    // project token can capture an event with this name, and it would count as a conversion.
    if (clickHouseEvent.event === COHORT_MEMBERSHIP_CHANGED_EVENT) {
        counterHogflowMatcherEventSkipped.labels({ reason: 'reserved_event_name' }).inc()
        return false
    }
    return true
}

// Person mutations arrive on clickhouse_person with the full current property set but no triggering
// analytics event. We synthesize a `$person_updated` event so wakeMatchingWorkflows can run a wait's
// property condition against the new person.properties. Event-name `events` entries never match this
// synthetic event name, which is correct: a person change should only satisfy property-based waits.
function convertClickhousePersonToWakeGlobals(
    data: ClickHousePerson,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`
    const properties = parseJSON(data.properties) as Record<string, any>
    const person: CyclotronPerson = {
        id: data.id,
        properties,
        name: getPersonDisplayName(team, data.id, properties),
        url: `${projectUrl}/person/${encodeURIComponent(data.id)}`,
    }
    return {
        project: { id: team.id, name: team.name, url: projectUrl },
        event: {
            uuid: new UUIDT().toString(),
            event: '$person_updated',
            // Empty so indexBatch only keys this on person_id. A person mutation has no triggering
            // distinct_id, and using the person UUID here would add a spurious (team_id, distinct_id)
            // lookup that matches a job only if its distinct_id happened to equal the UUID.
            distinct_id: '',
            properties: {},
            timestamp: data.timestamp,
            url: person.url,
            elements_chain: '',
        },
        person,
    }
}

type IndexedBatch = {
    teamIds: number[]
    // Parallel (teamId, id) pair arrays for the correlated lookup (see findParkedJobs).
    distinctTeamIds: number[]
    distinctIds: string[]
    personTeamIds: number[]
    personIds: string[]
    byDistinctId: Map<string, HogFunctionInvocationGlobals[]>
    byPersonId: Map<string, HogFunctionInvocationGlobals[]>
}

// Whether a workflow exits when its conversion goal is met. Only then does the matcher wake a
// parked job on a conversion match (so it can exit early); otherwise the conversion goal is
// measurement-only and must not perturb the job's progression.
function exitsOnConversion(hogflow: HogFlow): boolean {
    return (
        hogflow.exit_condition === 'exit_on_conversion' ||
        hogflow.exit_condition === 'exit_on_trigger_not_matched_or_conversion'
    )
}

// Skip teams whose hogflows have nothing the matcher can act on: no wait_until_condition step, and
// no event-based conversion goal. Event conversions are evaluated regardless of exit condition so
// the `conversion` metric is tracked even for flows that don't exit on conversion — only the *wake*
// decision (in wakeMatchingWorkflows) still depends on exitsOnConversion.
// The hogflow cache keeps one object per flow version, so the answer is kept per object.
const actionableFlows = new WeakMap<HogFlow, boolean>()

function hasWaitUntilOrConversion(hogflow: HogFlow): boolean {
    let actionable = actionableFlows.get(hogflow)
    if (actionable === undefined) {
        actionable =
            hogflow.actions.some((a: HogFlowAction) => a.type === 'wait_until_condition') || hasConversionGoal(hogflow)
        actionableFlows.set(hogflow, actionable)
    }
    return actionable
}

function hasConversionGoal(hogflow: HogFlow): boolean {
    // Property goals count: their watchers are evaluated against person-property changes, and gating
    // on `events` alone would skip the team before those watchers were ever read, leaving every
    // property-only goal permanently at zero conversions.
    if (hogflow.conversion?.filters?.length) {
        return true
    }
    const conversionEvents = hogflow.conversion?.events
    return Array.isArray(conversionEvents) && conversionEvents.length > 0
}

// A property goal can be met by any event that carries the person, so it admits every name.
function goalAdmitsEventName(hogflow: HogFlow, eventName: string): boolean {
    if (hogflow.conversion?.filters?.length) {
        return true
    }
    return (hogflow.conversion?.events ?? [])
        .filter(hasEventOrActionTarget)
        .some((eventConfig) => !rejectsEventName(eventConfig.filters, eventName))
}

function toMillis(value: HogFlow['updated_at']): number | null {
    if (value === undefined || value === null) {
        return null
    }
    const millis = value instanceof Date ? value.getTime() : typeof value === 'number' ? value : Date.parse(value)
    return Number.isFinite(millis) ? millis : null
}

// Compiled filters read `person.properties.<key>` by pushing the string 'person' as the root of the field
// chain. A literal 'person' value in a filter also matches, which only drops that entry for membership changes.
function readsPerson(bytecode: unknown): boolean {
    return Array.isArray(bytecode) && bytecode.includes('person')
}

function flowCallsRandom(flow: HogFlow): boolean {
    const waits = flow.actions.flatMap((action: HogFlowAction) =>
        action.type === 'wait_until_condition'
            ? [
                  action.config.condition?.filters?.bytecode,
                  ...(action.config.events ?? []).map((entry) => entry.filters?.bytecode),
              ]
            : []
    )
    const goals = (flow.conversion?.events ?? []).map((entry) => entry.filters?.bytecode)
    return [...waits, ...goals, flow.conversion?.bytecode].some(callsRandom)
}

async function couldConvert(flows: HogFlow[], filterGlobals: FilterGlobals, spent: () => boolean): Promise<boolean> {
    for (const flow of flows) {
        const goal = pinConversionGoal(flow)
        if (spent() || (goal && [goal.properties, ...(goal.events ?? [])].some(callsRandom))) {
            return true
        }
        if (goal && (await matchesPinnedGoal(goal, filterGlobals, flow.id))) {
            return true
        }
    }
    return false
}

// Whether the event meets any of the goals. Over budget, or for a goal that draws a random number, it answers
// true so the watchers are looked up and judged the usual way.
async function couldMatchPinnedGoals(
    entries: PinnedGoalEntry[],
    eventName: string,
    filterGlobals: FilterGlobals,
    eventsOnly: boolean,
    spent: () => boolean
): Promise<boolean> {
    for (const entry of entries) {
        if (spent()) {
            return true
        }
        if (entry.eventNames && !entry.eventNames.has(eventName)) {
            continue
        }
        if ([entry.goal.properties, ...(entry.goal.events ?? [])].some(callsRandom)) {
            return true
        }
        const goal: PinnedConversionGoal = eventsOnly
            ? { events: entry.goal.events?.filter((bytecode: unknown) => !readsPerson(bytecode)) }
            : entry.goal
        if (await matchesPinnedGoal(goal, filterGlobals, entry.functionId)) {
            return true
        }
    }
    return false
}

const currentGoalEntries = new WeakMap<HogFlow, PinnedGoalEntry | null>()

function currentGoalEntry(flow: HogFlow): PinnedGoalEntry | null {
    let entry = currentGoalEntries.get(flow)
    if (entry === undefined) {
        const goal = pinConversionGoal(flow)
        entry = goal
            ? { functionId: flow.id, goal, key: stableStringify(goal), eventNames: goalEventNames(flow) }
            : null
        currentGoalEntries.set(flow, entry)
    }
    return entry
}

// The names `rejectsEventName` lets through for the flow's goal, or null when any name passes. Mirrors
// goal_event_names in products/workflows/backend/services/conversion_goals.py.
function goalEventNames(flow: HogFlow): Set<string> | null {
    if (flow.conversion?.filters?.length) {
        return null
    }
    const names = new Set<string>()
    for (const eventConfig of (flow.conversion?.events ?? []).filter(hasEventOrActionTarget)) {
        // A run drops entries without bytecode when it saves its goal, so they cannot match any event.
        const bytecode = eventConfig.filters?.bytecode
        if (!Array.isArray(bytecode) || bytecode.length === 0) {
            continue
        }
        if (eventConfig.filters?.actions?.length || !Array.isArray(eventConfig.filters?.events)) {
            return null
        }
        for (const eventFilter of eventConfig.filters.events) {
            if (eventFilter.type !== 'events' || eventFilter.id == null) {
                return null
            }
            names.add(String(eventFilter.id))
        }
    }
    return names
}

// Postgres returns jsonb with its keys reordered, so goals are compared by a key-sorted encoding.
function stableStringify(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value.map(stableStringify).join(',')}]`
    }
    if (value && typeof value === 'object') {
        const object = value as Record<string, unknown>
        return `{${Object.keys(object)
            .sort()
            .map((key) => `${JSON.stringify(key)}:${stableStringify(object[key])}`)
            .join(',')}}`
    }
    return JSON.stringify(value) ?? 'null'
}

// A pinned goal converts when the property branch matches, or any event branch does. The two are
// independent detectors of the same goal, so they are OR'd — matching the UI, where a person who
// does either is converted.
async function matchesPinnedGoal(
    goal: PinnedConversionGoal,
    filterGlobals: FilterGlobals,
    hogFlowId: string
): Promise<'property' | 'event' | null> {
    const context = { hogFlowId }
    if (goal.properties?.length && (await runFilterBytecode(goal.properties, filterGlobals, context))) {
        return 'property'
    }
    for (const bytecode of goal.events ?? []) {
        if (await runFilterBytecode(bytecode, filterGlobals, context)) {
            return 'event'
        }
    }
    return null
}

// Single pass over the batch: dedup distinct/person ids, collect team ids,
// and bucket every event under all the keys it could match a candidate by.
function indexBatch(invocationGlobals: HogFunctionInvocationGlobals[]): IndexedBatch {
    const teamIds = new Set<number>()
    const distinctTeamIds: number[] = []
    const distinctIds: string[] = []
    const personTeamIds: number[] = []
    const personIds: string[] = []
    const byDistinctId = new Map<string, HogFunctionInvocationGlobals[]>()
    const byPersonId = new Map<string, HogFunctionInvocationGlobals[]>()

    for (const globals of invocationGlobals) {
        const teamId = globals.project.id
        teamIds.add(teamId)

        const distinctId = globals.event.distinct_id
        if (distinctId) {
            const key = `${teamId}:${distinctId}`
            if (!byDistinctId.has(key)) {
                distinctTeamIds.push(teamId)
                distinctIds.push(distinctId)
            }
            pushToMap(byDistinctId, key, globals)
        }
        const personId = globals.person?.id
        if (personId) {
            const key = `${teamId}:${personId}`
            if (!byPersonId.has(key)) {
                personTeamIds.push(teamId)
                personIds.push(personId)
            }
            pushToMap(byPersonId, key, globals)
        }
    }

    return {
        teamIds: [...teamIds],
        distinctTeamIds,
        distinctIds,
        personTeamIds,
        personIds,
        byDistinctId,
        byPersonId,
    }
}

function pushToMap<K, V>(map: Map<K, V[]>, key: K, value: V): void {
    const existing = map.get(key)
    if (existing) {
        existing.push(value)
    } else {
        map.set(key, [value])
    }
}

function collectCandidateGlobals(
    candidate: Pick<ParkedCandidate, 'teamId' | 'distinctId' | 'personId'>,
    byDistinctId: Map<string, HogFunctionInvocationGlobals[]>,
    byPersonId: Map<string, HogFunctionInvocationGlobals[]>
): HogFunctionInvocationGlobals[] {
    const seen = new Set<HogFunctionInvocationGlobals>()
    if (candidate.distinctId) {
        for (const g of byDistinctId.get(`${candidate.teamId}:${candidate.distinctId}`) ?? []) {
            seen.add(g)
        }
    }
    if (candidate.personId) {
        for (const g of byPersonId.get(`${candidate.teamId}:${candidate.personId}`) ?? []) {
            seen.add(g)
        }
    }
    return [...seen]
}

// Point the persisted personId at the merge survivor so the worker's re-resolution — which falls back
// to state.personId when the job has no distinct_id — lands on the survivor. Returns the new state
// buffer, or null if the state can't be parsed (leave the row untouched).
function rewriteStatePersonId(
    stateBuffer: Buffer,
    newPersonId: string,
    newVersion: number,
    jobId: string,
    fillingNullAnchor = false
): Buffer | null {
    try {
        const parsed = parseJSON(stateBuffer.toString('utf-8'))
        // Reject a repoint no newer than the one already applied. Repoints aren't Kafka-keyed, so a
        // delayed lower-version move (anon → A, v2) can arrive in a later batch than a higher one already
        // applied (anon → B, v3); without this watermark it would rewind the wait onto the obsolete
        // person A, and B's person-stream updates would no longer address the parked job.
        // A first mapping is exempt: it carries version 0, which no watermark can beat, and there is no
        // anchor to rewind — the caller has already scoped it to jobs with none.
        const appliedVersion = parsed.state?.personIdRepointVersion ?? 0
        if (!fillingNullAnchor && newVersion <= appliedVersion) {
            return null
        }
        // Flag the re-key so the worker resolves the person by this survivor personId, not the repointed
        // distinct_id whose ~1min cache still points at the pre-merge person (see personIdRepointed).
        parsed.state = {
            ...parsed.state,
            personId: newPersonId,
            personIdRepointed: true,
            personIdRepointVersion: newVersion,
        }
        // Mark the wake so the wait handler knows the matcher woke this job rather than a polling
        // re-check. currentAction is always a wait_until_condition here (re-key scope). The two causes
        // stay separate flags: counterHogflowRekeyWake judges whether waking on a merge is wasted churn,
        // so folding first-mapping fills into it would blend two causes into one ratio.
        if (parsed.state.currentAction) {
            parsed.state.currentAction = fillingNullAnchor
                ? { ...parsed.state.currentAction, anchorWake: true }
                : { ...parsed.state.currentAction, rekeyWake: true }
        }
        return Buffer.from(JSON.stringify(parsed))
    } catch (err) {
        logger.warn('Failed to parse state during distinct_id-move re-key', { jobId, err })
        return null
    }
}

type WaitUntilConditionAction = Extract<HogFlowAction, { type: 'wait_until_condition' }>

function eventsOnlyWait(wait: WaitUntilConditionAction): WaitUntilConditionAction {
    return {
        ...wait,
        config: {
            ...wait.config,
            condition: { filters: null },
            events: wait.config.events?.filter((eventConfig) => !readsPerson(eventConfig.filters?.bytecode)),
        },
    }
}

async function evaluateWaitWake(
    wait: WaitUntilConditionAction,
    candidateGlobals: HogFunctionInvocationGlobals[],
    filterGlobalsFor: (g: HogFunctionInvocationGlobals) => FilterGlobals,
    source: WakeSource,
    hogFlowId: string
): Promise<PendingWakeWrite['wakes'][string] | null> {
    if (source === 'person' && conditionNeedsRunGlobals(wait)) {
        return { kind: 'recheck' }
    }
    for (const globals of candidateGlobals) {
        if (await matchesWaitUntilCondition(wait, filterGlobalsFor(globals), { hogFlowId, actionId: wait.id })) {
            return {
                kind: 'match',
                eventName: globals.event.event,
                eventUuid: globals.event.uuid,
                eventTimestamp: globals.event.timestamp,
            }
        }
    }
    return null
}

type MatchOutcome = { state: Buffer; wake: boolean }

// Applies a batch match to a parked job's state. Returns the new state plus whether the job should
// be woken (`scheduled = NOW()`) and whether its conversion should be counted this run. Returns null
// when nothing changed (e.g. the conversion was already counted and there's no wake to apply).
function applyMatchToState(stateBuffer: Buffer, m: MatchedJob): MatchOutcome | null {
    try {
        const parsed = parseJSON(stateBuffer.toString('utf-8'))
        const updatedState: HogFlowInvocationContext = { ...parsed.state }

        let changed = false
        let wake = false

        // A matched wait_until_condition step resumes the job, tagged so the resume reads as an event
        // match rather than a timeout.
        if (m.stepMatched) {
            if (updatedState.currentAction) {
                updatedState.currentAction = {
                    ...updatedState.currentAction,
                    eventMatched: true,
                    eventMatchedEvent: m.eventName,
                    eventMatchedEventUuid: m.eventUuid,
                    eventMatchedEventTimestamp: m.eventTimestamp,
                }
                changed = true
                wake = true
            } else {
                // A parked wait_until_condition job should always carry its current action. Without it
                // we cannot tag the wake as an event match - skip the flag and continue, since the
                // conversion handling above is independent of currentAction and may still apply.
                logger.warn('Skipping eventMatched: no currentAction in state', { jobId: m.id })
            }
        }

        // A wake the matcher could not decide: no eventMatched, so the worker evaluates the condition
        // itself and re-parks when it still does not match.
        if (m.recheckMatched && !m.stepMatched) {
            if (updatedState.currentAction) {
                updatedState.currentAction = { ...updatedState.currentAction, recheckWake: true }
                changed = true
                wake = true
            }
        }

        // Only exit-on-conversion flows resume on a conversion match, so shouldExitEarly can exit. For
        // any other exit condition the goal is measurement-only and the run must not be rescheduled,
        // or we'd pull a parked job (e.g. one in a delay) forward. Counting happens on the watcher
        // either way, so a measurement-only flow needs no write here at all.
        if (m.conversionMatched && m.exitsOnConversion) {
            updatedState.conversionMatched = true
            changed = true
            wake = true
        }

        if (!changed) {
            return null
        }
        parsed.state = updatedState
        return { state: Buffer.from(JSON.stringify(parsed)), wake }
    } catch (err) {
        logger.warn('Failed to parse state during match', { jobId: m.id, err })
        return null
    }
}
