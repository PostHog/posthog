import { Message } from 'node-rdkafka'
import { Pool } from 'pg'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HogFlowAction } from '../../schema/hogflow'
import { HealthCheckResult, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { HogFlowInvocationContext, HogFunctionInvocationGlobals } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseConfig, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

type ParkedJob = {
    id: string
    teamId: number
    functionId: string
    state: HogFlowInvocationContext
    rawState: Buffer
}

/**
 * Dedicated consumer that matches incoming events against parked hogflow jobs
 * (wait_until_condition, conversion goals) and wakes them when conditions are met.
 *
 * For each event batch, the consumer:
 * 1. Finds all parked hogflow jobs for the event's distinct_id via cyclotron_jobs
 * 2. Loads the hogflow config from cache to determine what each step is waiting for
 * 3. Evaluates the step's filters against the incoming event
 * 4. Wakes matching jobs by setting scheduled = NOW() and eventMatched = true
 *
 * Lives in its own deployment so that failures talking to the Cyclotron V2
 * database do not block `cdp-events-consumer`.
 */
export class CdpHogflowSubscriptionMatcherConsumer extends CdpConsumerBase {
    protected name = 'CdpHogflowSubscriptionMatcherConsumer'
    protected kafkaConsumer: KafkaConsumer
    private cyclotronPool: Pool | null = null

    constructor(config: CdpConsumerBaseConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = new KafkaConsumer({
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

    /**
     * For each event in the batch, find parked hogflow jobs for the same
     * distinct_id, load the hogflow config from cache, evaluate the current
     * step's conditions against the event, and wake matching jobs.
     */
    @instrumented('cdpHogflowSubscriptionMatcher.wakeMatchingWorkflows')
    private async wakeMatchingWorkflows(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        if (!this.cyclotronPool) {
            return
        }

        // Collect unique (team_id, distinct_id) lookup keys from the event batch.
        const globalsByKey = new Map<string, HogFunctionInvocationGlobals>()

        for (const globals of invocationGlobals) {
            const distinctId = globals.event.distinct_id
            if (!distinctId) {
                continue
            }
            const key = `${globals.project.id}:${distinctId}`
            if (!globalsByKey.has(key)) {
                globalsByKey.set(key, globals)
            }
        }

        if (globalsByKey.size === 0) {
            return
        }

        // Find parked hogflow jobs matching those distinct_ids.
        const teamIds = [...new Set([...globalsByKey.values()].map((g) => g.project.id))]
        const distinctIds = [...new Set([...globalsByKey.values()].map((g) => g.event.distinct_id))]

        const parkedJobs = await this.findParkedJobs(teamIds, distinctIds)
        if (parkedJobs.length === 0) {
            return
        }

        // Load hogflow configs for the parked jobs.
        const hogflowIds = [...new Set(parkedJobs.map((j) => j.functionId))]
        const hogflows = await this.hogFlowManager.getHogFlows(hogflowIds)

        // Evaluate each parked job against the incoming event.
        const jobsToWake: { id: string; state: Buffer }[] = []

        for (const job of parkedJobs) {
            const hogflow = hogflows[job.functionId]
            if (!hogflow) {
                continue
            }

            const currentActionId = job.state.currentAction?.id
            if (!currentActionId) {
                continue
            }

            const action = hogflow.actions.find((a: HogFlowAction) => a.id === currentActionId)
            if (!action) {
                continue
            }

            // Only evaluate wait steps that are actively parked.
            if (action.type !== 'wait_until_condition') {
                continue
            }

            // Find the globals for this job's team + distinct_id.
            const distinctId = job.state.event?.distinct_id || job.state.personId
            const lookupKey = `${job.teamId}:${distinctId}`
            const globals = globalsByKey.get(lookupKey)
            if (!globals) {
                continue
            }

            const matched = await this.evaluateStepFilters(action, globals)
            if (matched) {
                // Mark eventMatched in the state so the handler knows this was
                // a match (not a timeout) on re-entry.
                const updatedState = { ...job.state }
                if (updatedState.currentAction) {
                    updatedState.currentAction = { ...updatedState.currentAction, eventMatched: true }
                }

                // Re-serialize the full state blob (preserving queueParameters/queueMetadata).
                const rawParsed = parseJSON(job.rawState.toString('utf-8'))
                rawParsed.state = updatedState
                const newRawState = Buffer.from(JSON.stringify(rawParsed))

                jobsToWake.push({ id: job.id, state: newRawState })
            }
        }

        if (jobsToWake.length === 0) {
            return
        }

        const woken = await this.wakeJobs(jobsToWake)
        logger.info('⚡', 'Woke waiting workflows from event match', {
            evaluated: parkedJobs.length,
            matched: jobsToWake.length,
            woken,
        })
    }

    /**
     * Evaluate a wait_until_condition step's filters against the incoming event.
     * Either an event match or a property condition match wakes the step.
     */
    private async evaluateStepFilters(
        action: Extract<HogFlowAction, { type: 'wait_until_condition' }>,
        globals: HogFunctionInvocationGlobals
    ): Promise<boolean> {
        const filterGlobals = convertToHogFunctionFilterGlobal(globals)

        for (const eventConfig of action.config.events ?? []) {
            if (await this.evaluateEventConfig(eventConfig, globals, filterGlobals, action.id)) {
                return true
            }
        }

        const bytecode = action.config.condition?.filters?.bytecode
        if (Array.isArray(bytecode) && bytecode.length > 0) {
            try {
                const result = await execHog(bytecode, { globals: filterGlobals })
                if (result.execResult?.result === true) {
                    return true
                }
            } catch (err) {
                logger.warn('Filter evaluation error for wait_until_condition', {
                    actionId: action.id,
                    error: String(err),
                })
            }
        }

        return false
    }

    private async evaluateEventConfig(
        eventConfig: { filters?: any },
        globals: HogFunctionInvocationGlobals,
        filterGlobals: ReturnType<typeof convertToHogFunctionFilterGlobal>,
        actionId: string
    ): Promise<boolean> {
        const bytecode = eventConfig.filters?.bytecode
        if (Array.isArray(bytecode) && bytecode.length > 0) {
            try {
                const result = await execHog(bytecode, { globals: filterGlobals })
                return result.execResult?.result === true
            } catch (err) {
                logger.warn('Event filter evaluation error', { actionId, error: String(err) })
                return false
            }
        }

        // No bytecode: match on event name alone. An empty event list matches nothing.
        const configuredNames = extractEventNames(eventConfig.filters)
        return configuredNames.includes(globals.event.event)
    }

    /**
     * Find parked hogflow jobs for the given team_ids and distinct_ids.
     * A job is "parked" when status = 'available' and scheduled is in the future.
     */
    private async findParkedJobs(teamIds: number[], distinctIds: string[]): Promise<ParkedJob[]> {
        if (!this.cyclotronPool) {
            return []
        }

        const result = await this.cyclotronPool.query(
            `SELECT id, team_id, function_id, state
             FROM cyclotron_jobs
             WHERE status = 'available'
               AND queue_name = 'hogflow'
               AND scheduled > NOW()
               AND team_id = ANY($1::int[])
               AND distinct_id = ANY($2::text[])`,
            [teamIds, distinctIds]
        )

        const jobs: ParkedJob[] = []
        for (const row of result.rows) {
            if (!row.state) {
                continue
            }
            try {
                const parsed = parseJSON(row.state.toString('utf-8'))
                jobs.push({
                    id: row.id,
                    teamId: row.team_id,
                    functionId: row.function_id,
                    state: parsed.state as HogFlowInvocationContext,
                    rawState: row.state,
                })
            } catch (err) {
                logger.warn('Failed to parse parked job state', { jobId: row.id, error: String(err) })
            }
        }

        return jobs
    }

    /**
     * Wake jobs by setting scheduled = NOW() and updating their state.
     * Only affects jobs that are still 'available' (not picked up by a worker).
     */
    private async wakeJobs(jobs: { id: string; state: Buffer }[]): Promise<number> {
        if (!this.cyclotronPool || jobs.length === 0) {
            return 0
        }

        let woken = 0
        for (const job of jobs) {
            const result = await this.cyclotronPool.query(
                `UPDATE cyclotron_jobs
                 SET scheduled = NOW(), state = $2
                 WHERE id = $1 AND status = 'available'`,
                [job.id, job.state]
            )
            woken += result.rowCount ?? 0
        }
        return woken
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
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

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

function extractEventNames(filters: any): string[] {
    if (!filters || typeof filters !== 'object') {
        return []
    }
    const events = filters.events
    if (!Array.isArray(events) || events.length === 0) {
        return []
    }
    return events
        .map((e: any) => (e && typeof e === 'object' ? (e.id ?? e.name ?? '') : ''))
        .filter((name: string) => name !== '')
}
