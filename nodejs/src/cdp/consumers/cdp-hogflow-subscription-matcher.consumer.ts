import { Message } from 'node-rdkafka'
import { Pool } from 'pg'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '../../kafka/consumer'
import { HogFlow, HogFlowAction } from '../../schema/hogflow'
import { HealthCheckResult, PluginsServerConfig, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { HogFlowInvocationContext, HogFunctionInvocationGlobals } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

type ParkedCandidate = {
    id: string
    teamId: number
    functionId: string
    actionId: string | null
    distinctId: string | null
    personId: string | null
}

type WakeRequest = {
    id: string
    stepMatched: boolean
    conversionMatched: boolean
}

type FilterGlobals = ReturnType<typeof convertToHogFunctionFilterGlobal>

// Wakes parked hogflow jobs when an event matches a `wait_until_condition` step
// or a workflow conversion goal. No-op when `CYCLOTRON_NODE_DATABASE_URL` is unset.
export class CdpHogflowSubscriptionMatcherConsumer<
    TConfig extends PluginsServerConfig = PluginsServerConfig,
> extends CdpConsumerBase<TConfig> {
    protected name = 'CdpHogflowSubscriptionMatcherConsumer'
    protected kafkaConsumer: KafkaConsumerInterface
    private cyclotronPool: Pool | null = null

    constructor(config: TConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-hogflow-subscription-matcher-consumer',
            topic: KAFKA_EVENTS_JSON,
        })

        if (config.CYCLOTRON_NODE_DATABASE_URL) {
            this.cyclotronPool = new Pool({
                connectionString: config.CYCLOTRON_NODE_DATABASE_URL,
                max: 5,
            })
        }
    }

    public async processBatch(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        if (!invocationGlobals.length) {
            return
        }
        await this.wakeMatchingWorkflows(invocationGlobals)
    }

    @instrumented('cdpHogflowSubscriptionMatcher.wakeMatchingWorkflows')
    private async wakeMatchingWorkflows(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        if (!this.cyclotronPool) {
            return
        }

        const { teamIds, distinctIds, personIds, byDistinctId, byPersonId } = indexBatch(invocationGlobals)
        if (byDistinctId.size === 0 && byPersonId.size === 0) {
            return
        }

        const candidates = await this.findParkedJobs(teamIds, distinctIds, personIds)
        if (candidates.length === 0) {
            return
        }

        const hogflows = await this.hogFlowManager.getHogFlows([...new Set(candidates.map((c) => c.functionId))])

        // Compute filterGlobals once per event; the same event can match many candidates.
        const filterGlobalsByEvent = new Map<HogFunctionInvocationGlobals, FilterGlobals>()
        const filterGlobalsFor = (g: HogFunctionInvocationGlobals): FilterGlobals => {
            let fg = filterGlobalsByEvent.get(g)
            if (!fg) {
                fg = convertToHogFunctionFilterGlobal(g)
                filterGlobalsByEvent.set(g, fg)
            }
            return fg
        }

        const jobsToWake: WakeRequest[] = []
        for (const candidate of candidates) {
            const hogflow = hogflows[candidate.functionId]
            if (!hogflow) {
                continue
            }

            const candidateGlobals = collectCandidateGlobals(candidate, byDistinctId, byPersonId)
            if (candidateGlobals.length === 0) {
                continue
            }

            const action = candidate.actionId
                ? hogflow.actions.find((a: HogFlowAction) => a.id === candidate.actionId)
                : undefined

            // Any single matching event is enough. Stop early once both flags are set.
            let stepMatched = false
            let conversionMatched = false
            for (const globals of candidateGlobals) {
                const filterGlobals = filterGlobalsFor(globals)
                if (!stepMatched && action?.type === 'wait_until_condition') {
                    stepMatched = await this.evaluateWaitUntilCondition(action, filterGlobals, globals.event.event)
                }
                if (!conversionMatched) {
                    conversionMatched = await this.evaluateConversionEvents(hogflow, filterGlobals, globals.event.event)
                }
                if (stepMatched && conversionMatched) {
                    break
                }
            }

            if (stepMatched || conversionMatched) {
                jobsToWake.push({ id: candidate.id, stepMatched, conversionMatched })
            }
        }

        if (jobsToWake.length === 0) {
            return
        }

        const woken = await this.wakeJobs(jobsToWake)
        logger.info('⚡', 'Woke waiting workflows from event match', {
            evaluated: candidates.length,
            matched: jobsToWake.length,
            woken,
        })
    }

    private async evaluateWaitUntilCondition(
        action: Extract<HogFlowAction, { type: 'wait_until_condition' }>,
        filterGlobals: FilterGlobals,
        incomingEventName: string
    ): Promise<boolean> {
        // `events` is populated by phase 2 of the wait-until-event RFC; for now the
        // field is absent from the schema.
        const events = (action.config as any).events as { filters?: any }[] | undefined
        for (const eventConfig of events ?? []) {
            if (await this.evaluateEventConfig(eventConfig, filterGlobals, incomingEventName, action.id)) {
                return true
            }
        }
        return runBytecode(action.config.condition?.filters?.bytecode, filterGlobals, action.id)
    }

    private async evaluateConversionEvents(
        hogflow: HogFlow,
        filterGlobals: FilterGlobals,
        incomingEventName: string
    ): Promise<boolean> {
        const conversionEvents = ((hogflow.conversion as any)?.events ?? []) as { filters?: any }[]
        const contextId = `${hogflow.id}/conversion`
        for (const eventConfig of conversionEvents) {
            if (await this.evaluateEventConfig(eventConfig, filterGlobals, incomingEventName, contextId)) {
                return true
            }
        }
        return false
    }

    private async evaluateEventConfig(
        eventConfig: { filters?: any },
        filterGlobals: FilterGlobals,
        incomingEventName: string,
        contextId: string
    ): Promise<boolean> {
        const bytecode = eventConfig.filters?.bytecode
        if (Array.isArray(bytecode) && bytecode.length > 0) {
            return runBytecode(bytecode, filterGlobals, contextId)
        }
        // Fallback when bytecode is absent: match the event name directly.
        return extractEventNames(eventConfig.filters).includes(incomingEventName)
    }

    private async findParkedJobs(
        teamIds: number[],
        distinctIds: string[],
        personIds: string[]
    ): Promise<ParkedCandidate[]> {
        if (!this.cyclotronPool) {
            return []
        }

        const result = await this.cyclotronPool.query(
            `SELECT id, team_id, function_id, action_id, distinct_id, person_id
             FROM cyclotron_jobs
             WHERE status = 'available'
               AND queue_name = 'hogflow'
               AND scheduled > NOW()
               AND team_id = ANY($1::int[])
               AND (distinct_id = ANY($2::text[]) OR person_id = ANY($3::uuid[]))`,
            [teamIds, distinctIds, personIds]
        )

        return result.rows.map((row) => ({
            id: row.id,
            teamId: row.team_id,
            functionId: row.function_id,
            actionId: row.action_id,
            distinctId: row.distinct_id,
            personId: row.person_id,
        }))
    }

    private async wakeJobs(requests: WakeRequest[]): Promise<number> {
        if (!this.cyclotronPool || requests.length === 0) {
            return 0
        }

        const ids = requests.map((r) => r.id)
        const stateRows = await this.cyclotronPool.query(
            `SELECT id, state FROM cyclotron_jobs
             WHERE id = ANY($1::uuid[]) AND status = 'available'`,
            [ids]
        )

        const requestById = new Map(requests.map((r) => [r.id, r]))
        const updates: { id: string; state: Buffer }[] = []
        for (const row of stateRows.rows) {
            if (!row.state) {
                continue
            }
            const req = requestById.get(row.id)
            if (!req) {
                continue
            }
            const updated = applyWakeFlags(row.state, req)
            if (updated) {
                updates.push({ id: row.id, state: updated })
            }
        }

        if (updates.length === 0) {
            return 0
        }

        const result = await this.cyclotronPool.query(
            `UPDATE cyclotron_jobs cj
             SET scheduled = NOW(), state = u.state
             FROM (
                 SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state
             ) u
             WHERE cj.id = u.id AND cj.status = 'available'`,
            [updates.map((u) => u.id), updates.map((u) => u.state)]
        )
        return result.rowCount ?? 0
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent
                    if (!clickHouseEvent.person_id) {
                        return
                    }
                    const team = await this.deps.teamManager.getTeam(clickHouseEvent.team_id)
                    if (!team) {
                        return
                    }
                    events.push(convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.config.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, { size: messages.length })
            return await instrumentFn('cdpHogflowSubscriptionMatcher.handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                const backgroundTask = this.processBatch(invocationGlobals).catch((err) => {
                    captureException(err)
                    logger.error('🔴', 'Error matching workflows', { err })
                })
                return { backgroundTask }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.kafkaConsumer.disconnect()
        if (this.cyclotronPool) {
            await this.cyclotronPool.end()
        }
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

type IndexedBatch = {
    teamIds: number[]
    distinctIds: string[]
    personIds: string[]
    byDistinctId: Map<string, HogFunctionInvocationGlobals[]>
    byPersonId: Map<string, HogFunctionInvocationGlobals[]>
}

// Single pass over the batch: dedup distinct/person ids, collect team ids,
// and bucket every event under all the keys it could match a candidate by.
function indexBatch(invocationGlobals: HogFunctionInvocationGlobals[]): IndexedBatch {
    const teamIds = new Set<number>()
    const distinctIds = new Set<string>()
    const personIds = new Set<string>()
    const byDistinctId = new Map<string, HogFunctionInvocationGlobals[]>()
    const byPersonId = new Map<string, HogFunctionInvocationGlobals[]>()

    for (const globals of invocationGlobals) {
        const teamId = globals.project.id
        if (typeof teamId === 'number') {
            teamIds.add(teamId)
        }
        const distinctId = globals.event.distinct_id
        if (distinctId) {
            distinctIds.add(distinctId)
            pushToMap(byDistinctId, `${teamId}:${distinctId}`, globals)
        }
        const personId = globals.person?.id
        if (personId) {
            personIds.add(personId)
            pushToMap(byPersonId, `${teamId}:${personId}`, globals)
        }
    }

    return {
        teamIds: [...teamIds],
        distinctIds: [...distinctIds],
        personIds: [...personIds],
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
    candidate: ParkedCandidate,
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

async function runBytecode(bytecode: unknown, filterGlobals: FilterGlobals, contextId: string): Promise<boolean> {
    if (!Array.isArray(bytecode) || bytecode.length === 0) {
        return false
    }
    try {
        const result = await execHog(bytecode, { globals: filterGlobals })
        return result.execResult?.result === true
    } catch (err) {
        logger.warn('Bytecode evaluation error', { contextId, err })
        return false
    }
}

function applyWakeFlags(stateBuffer: Buffer, req: WakeRequest): Buffer | null {
    try {
        const parsed = parseJSON(stateBuffer.toString('utf-8'))
        const updatedState: HogFlowInvocationContext = { ...parsed.state }
        if (req.stepMatched && updatedState.currentAction) {
            updatedState.currentAction = { ...updatedState.currentAction, eventMatched: true }
        }
        if (req.conversionMatched) {
            updatedState.conversionMatched = true
        }
        parsed.state = updatedState
        return Buffer.from(JSON.stringify(parsed))
    } catch (err) {
        logger.warn('Failed to parse state during wake', { jobId: req.id, err })
        return null
    }
}

function extractEventNames(filters: any): string[] {
    const events = filters && typeof filters === 'object' ? filters.events : undefined
    if (!Array.isArray(events) || events.length === 0) {
        return []
    }
    return events
        .map((e: any) => (e && typeof e === 'object' ? (e.id ?? e.name ?? '') : ''))
        .filter((name: string) => name !== '')
}
