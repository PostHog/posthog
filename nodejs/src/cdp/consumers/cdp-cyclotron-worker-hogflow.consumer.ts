import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { PluginsServerConfig, Team } from '~/types'

import { isRowScopedTrigger } from '../schema/hogflow'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { PERSON_CACHE_MAX_STALENESS_MS } from '../services/managers/persons-manager.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    CyclotronPerson,
    HogFlowInvocationContext,
} from '../types'
import { getPersonDisplayName } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

type LoadHogFlowsResult = {
    loadedInvocations: CyclotronJobInvocationHogFlow[]
    canceledResults: CyclotronJobInvocationResult[]
}

// How long after an event was captured its own person writes can still be missing from the person
// copy this worker resolves. That copy comes from a cache that lags the database by at most
// PERSON_CACHE_MAX_STALENESS_MS; the rest is margin for the lag between capture and the person write.
const EVENT_PERSON_WRITE_OVERLAY_WINDOW_MS = PERSON_CACHE_MAX_STALENESS_MS + 4 * 60 * 1000

/**
 * The trigger event's `$set` block, when it is still worth replaying onto the person.
 *
 * A person copy comes from a cache that can lag the database, so a property the trigger event sets
 * can be absent from it. Most visibly an email: a message step then renders an empty `to` and the
 * send fails with no recipient.
 *
 * Only `$set` replays. `$set_once` resolves against the real person row, which this worker does not
 * have, so replaying it would invent a value the database rejected.
 *
 * The event must also be recent. The bound is on the event's age, not on the age of the cached copy,
 * which the person manager does not expose. It is therefore approximate in both directions: inside
 * the window a trigger value can beat a newer cached one, and a capture-to-ingestion lag longer than
 * the margin skips the replay. It exists to stop the far worse case of a run resumed after a wait
 * pinning trigger-time values, which would address a day-7 drip email to a mailbox the person
 * replaced on day 2.
 *
 * The window is two-sided. `timestamp` is the fallback when the server did not stamp `captured_at`,
 * and a client clock that runs fast makes an old event look recent forever.
 */
function replayablePersonWrites(event: HogFlowInvocationContext['event']): Record<string, any> | undefined {
    const capturedAt = Date.parse(event.captured_at ?? event.timestamp)
    if (!Number.isFinite(capturedAt) || Math.abs(Date.now() - capturedAt) > EVENT_PERSON_WRITE_OVERLAY_WINDOW_MS) {
        return undefined
    }

    const set = event.properties?.$set
    return set && typeof set === 'object' && !Array.isArray(set) ? (set as Record<string, any>) : undefined
}

function applyPersonWrites(
    team: Team,
    person: CyclotronPerson,
    writes: Record<string, any>,
    personIdOrDistinctId: string
): CyclotronPerson {
    const properties = { ...person.properties, ...writes }

    return {
        ...person,
        properties,
        // The display name derives from these properties, so recompute it. Otherwise a template can
        // greet the old email address in the message it sends to the new one.
        name: getPersonDisplayName(team, personIdOrDistinctId, properties),
    }
}

export class CdpCyclotronWorkerHogFlow extends CdpCyclotronWorker {
    protected override name = 'CdpCyclotronWorkerHogFlow'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue, 'hogflow')
    }

    @instrumented('cdpConsumer.handleEachBatch.executeInvocations')
    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const { loadedInvocations, canceledResults } = await this.loadHogFlows(invocations)
        const executed = await Promise.all(loadedInvocations.map((item) => this.hogFlowExecutor.execute(item)))
        return [...canceledResults, ...executed]
    }

    /**
     * Terminate an invocation as canceled through the normal result pipeline, so the
     * terminal lifecycle row, app metric, and run log all land. A bare cyclotron
     * status flip would leave the run showing 'running' in the Invocations UI forever.
     */
    private buildCanceledResult(
        item: CyclotronJobInvocation,
        message: string,
        hogFlow?: HogFlow
    ): CyclotronJobInvocationResult {
        // The monitoring services identify a workflow result by the presence of `hogFlow`, and use
        // it to key the terminal lifecycle row as `hog_flow` and to fill the row's trigger fields.
        // Without it the row keys as `hog_function`; because `function_kind` is part of the
        // ReplacingMergeTree key, that row could never collapse the `running` row (written as
        // `hog_flow`), leaving the run stuck at 'running' in the Invocations tab. When the live flow
        // is gone (deleted, or its lookup failed) we still know its id, which is `item.functionId`,
        // so attach a minimal stub carrying just that so the row still keys as `hog_flow`. Only `id`
        // is read off this object on the cancellation path.
        const resolvedFlow = hogFlow ?? ({ id: item.functionId } as HogFlow)
        const invocation = { ...item, hogFlow: resolvedFlow }
        const result = createInvocationResult(invocation, {}, { finished: true })
        result.canceled = true
        result.logs.push({ level: 'info', timestamp: DateTime.now(), message })
        result.metrics.push({
            team_id: item.teamId,
            app_source_id: item.parentRunId ?? item.functionId,
            instance_id: (item.state as CyclotronJobInvocationHogFlow['state'] | null)?.currentAction?.id,
            metric_kind: 'other',
            metric_name: 'canceled',
            count: 1,
        })
        return result
    }

    @instrumented('cdpConsumer.handleEachBatch.loadHogFlows')
    protected async loadHogFlows(invocations: CyclotronJobInvocation[]): Promise<LoadHogFlowsResult> {
        const loadedInvocations: CyclotronJobInvocationHogFlow[] = []
        const failedInvocations: CyclotronJobInvocation[] = []
        const canceledResults: CyclotronJobInvocationResult[] = []

        await Promise.all(
            invocations.map(async (item) => {
                // Checked before the team/flow lookups so a cancel-requested run terminates even
                // when its flow or team has since been deleted. The flow lookup here is
                // best-effort and only sets the terminal row's function_kind: a null flow
                // (deleted) or a lookup error still cancels.
                if (item.cancelRequestedAt) {
                    const hogFlow = await this.hogFlowManager.getHogFlow(item.functionId).catch(() => null)
                    canceledResults.push(this.buildCanceledResult(item, 'Run canceled', hogFlow ?? undefined))
                    return
                }

                const team = await this.deps.teamManager.getTeam(item.teamId)
                const hogFlow = await this.hogFlowManager.getHogFlow(item.functionId)
                if (!hogFlow || !team) {
                    logger.error('⚠️', 'Error finding hog flow', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

                    return
                }

                // A run waking while its workflow is disabled/archived is canceled rather
                // than executed. Runs that wake while the workflow is active proceed
                // normally, so re-enabling before a parked run's wake time releases it.
                if (hogFlow.status !== 'active') {
                    logger.info('⏭️', 'Cancelling hog flow invocation - workflow is no longer active', {
                        id: item.functionId,
                        status: hogFlow.status,
                    })

                    canceledResults.push(
                        this.buildCanceledResult(item, 'Run canceled: the workflow is no longer active', hogFlow)
                    )

                    return
                }

                const hogFlowInvocationState = item.state as CyclotronJobInvocationHogFlow['state']

                // Row-scoped invocations (a warehouse row, a Slack message, a GitHub event) don't have
                // a real person — the delivery is the unit of work and person-dependent steps no-op for
                // these flows. Explicitly skip the person lookup rather than relying on
                // event.distinct_id being empty so future changes to the synthetic event shape don't
                // accidentally re-enable the lookup.
                const isRowScoped = isRowScopedTrigger(hogFlow.trigger)
                // Account-audience batch invocations carry the account's group key as
                // event.distinct_id; resolving it as a person distinct_id would attach an
                // unrelated person to the run. Accounts have no person — skip the lookup.
                // The state stamp wins over the live trigger, which may have been edited to a
                // person audience while these children were queued; the trigger check remains
                // as a fallback for jobs enqueued before the stamp existed.
                const isAccountAudience =
                    hogFlowInvocationState.accountAudience === true ||
                    (hogFlow.trigger?.type === 'batch' && hogFlow.trigger.filters?.audience_type === 'accounts')
                // The matcher wrote this job's personId anchor: a merge repointed the distinct_id onto a
                // survivor, or the distinct_id acquired its first person. Resolve by that personId so the step
                // reads the right person — resolving by the distinct_id would hit its stale ~1min cache entry
                // (the pre-merge person, or none at all) and e.g. drop an email.
                const resolveByRepointedPerson =
                    hogFlowInvocationState.personIdRepointed === true && !!hogFlowInvocationState.personId
                // One-shot: consume the flag on this wake-resolution only. Later steps fall back to normal
                // distinct_id-first resolution, which self-heals to the latest survivor if the distinct_id is
                // repointed again (a second merge onto a non-wait step is out of processMoveBatch's scope).
                if (resolveByRepointedPerson) {
                    delete hogFlowInvocationState.personIdRepointed
                }
                const personIdOrDistinctId =
                    isRowScoped || isAccountAudience
                        ? undefined
                        : resolveByRepointedPerson
                          ? hogFlowInvocationState.personId
                          : hogFlowInvocationState.event.distinct_id || hogFlowInvocationState.personId
                const kind =
                    resolveByRepointedPerson || !hogFlowInvocationState.event.distinct_id ? 'person_id' : 'distinct_id'

                // Only event triggers fire on an event that can carry person writes. Batch and
                // row-scoped invocations carry a synthetic event, whose properties are not the
                // person's.
                const personWrites =
                    hogFlow.trigger?.type === 'event' ? replayablePersonWrites(hogFlowInvocationState.event) : undefined

                const [initialPerson, groups] = await Promise.all([
                    personIdOrDistinctId
                        ? this.personsManager.getCyclotronPerson(hogFlow.team_id, personIdOrDistinctId, kind)
                        : undefined,
                    this.groupsManager.getGroupsForEvent(
                        hogFlow.team_id,
                        hogFlowInvocationState.event.properties,
                        `${this.config.SITE_URL}/project/${hogFlow.team_id}`
                    ),
                ])

                // The person read is eventually consistent and caches a miss for as long as it caches
                // a hit, so a person the trigger event just created can stay unresolved for the whole
                // window, and the send drops for want of a recipient. Read again uncached, but only
                // when the event carries the writes that would have created the person, so an
                // anonymous distinct id that has no person still costs one read.
                let resolvedPerson = initialPerson
                if (!resolvedPerson && personWrites && personIdOrDistinctId) {
                    resolvedPerson = await this.personsManager.getCyclotronPerson(
                        hogFlow.team_id,
                        personIdOrDistinctId,
                        kind,
                        { forceFresh: true }
                    )
                }

                const person =
                    resolvedPerson && personWrites && personIdOrDistinctId
                        ? applyPersonWrites(team, resolvedPerson, personWrites, personIdOrDistinctId)
                        : resolvedPerson

                if (!person && hogFlow.trigger?.type === 'event') {
                    logger.warn('⚠️', 'Person not found for hog flow invocation', {
                        hogFlowId: hogFlow.id,
                        distinctId: hogFlowInvocationState.event?.distinct_id || hogFlowInvocationState.personId,
                        invocationId: item.id,
                    })
                }

                // Batch-triggered invocations arrive with an empty event.distinct_id because the
                // blast-radius query returns UUIDs only. The person lookup above resolves one
                // distinct_id for us (when the person has any), so backfill it here so templates
                // defaulting to `{event.distinct_id}` resolve at hog runtime.
                if (!hogFlowInvocationState.event.distinct_id && person?.distinct_id) {
                    hogFlowInvocationState.event.distinct_id = person.distinct_id
                }

                // Persist the resolved person UUID into state so a re-parked wait keeps its person_id
                // even when a later re-resolution transiently misses. clickhouse_person wakes match on
                // person_id only, so a wait parked with person_id = null could never be woken by a
                // person-property change — it would depend entirely on the polling backstop.
                if (person?.id && !hogFlowInvocationState.personId) {
                    hogFlowInvocationState.personId = person.id
                }

                const filterGlobals = convertToHogFunctionFilterGlobal({
                    event: hogFlowInvocationState.event,
                    person: person ?? undefined,
                    groups,
                    variables: hogFlowInvocationState.variables || {},
                })

                const loaded: CyclotronJobInvocationHogFlow = {
                    ...item,
                    state: hogFlowInvocationState,
                    hogFlow,
                    person: person ?? undefined,
                    groups,
                    filterGlobals,
                }

                if (personIdOrDistinctId) {
                    // This read is uncached, so it does not replay the trigger's writes. A wait exists
                    // to act on the person as they are now, and replaying here would let a trigger
                    // value beat a newer one the wait was waiting for.
                    loaded.refreshPerson = async () => {
                        const fresh = await this.personsManager.getCyclotronPerson(
                            hogFlow.team_id,
                            personIdOrDistinctId,
                            kind,
                            { forceFresh: true }
                        )
                        return {
                            person: fresh ?? undefined,
                            filterGlobals: convertToHogFunctionFilterGlobal({
                                event: hogFlowInvocationState.event,
                                person: fresh ?? undefined,
                                groups,
                                variables: hogFlowInvocationState.variables || {},
                            }),
                        }
                    }
                }

                loadedInvocations.push(loaded)
            })
        )

        await this.cyclotronJobQueue.dequeueInvocations(failedInvocations)

        return { loadedInvocations, canceledResults }
    }
}
