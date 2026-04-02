import { Counter, Gauge } from 'prom-client'
import { z } from 'zod'

import { InternalFetchService } from '~/common/services/internal-fetch'
import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS } from '~/config/kafka-topics'
import { KafkaProducerWrapper } from '~/kafka/producer'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    PluginsServerConfig,
} from '~/types'
import { parseJSON } from '~/utils/json-parse'
import { logger } from '~/utils/logger'

const schedulerPollCounter = new Counter({
    name: 'cdp_hogflow_scheduler_polls',
    help: 'Number of scheduler poll cycles completed',
    labelNames: ['status'],
})

const schedulerDispatchedCounter = new Counter({
    name: 'cdp_hogflow_scheduler_dispatched',
    help: 'Number of batch triggers dispatched to Kafka',
})

const schedulerInitializedCounter = new Counter({
    name: 'cdp_hogflow_scheduler_initialized',
    help: 'Number of schedules initialized with next_run_at',
})

const schedulerFailedCounter = new Counter({
    name: 'cdp_hogflow_scheduler_failed',
    help: 'Number of schedule processing failures',
    labelNames: ['stage'],
})

const schedulerPollDurationGauge = new Gauge({
    name: 'cdp_hogflow_scheduler_poll_duration_ms',
    help: 'Duration of the last poll cycle in milliseconds',
})

const ProcessedScheduleSchema = z.object({
    schedule_id: z.string(),
    team_id: z.number(),
    hog_flow_id: z.string(),
    filters: z.record(z.unknown()),
    variables: z.record(z.unknown()),
})

const ProcessDueSchedulesResponseSchema = z.object({
    processed: z.array(ProcessedScheduleSchema),
    initialized: z.array(z.string()),
    failed: z.array(z.string()),
})

type ProcessedSchedule = z.infer<typeof ProcessedScheduleSchema>

export class HogFlowScheduleService {
    private kafkaProducer: KafkaProducerWrapper | null = null
    private running = false
    private pollPromise: Promise<void> | null = null
    private sleepResolve: (() => void) | null = null
    private consecutiveFailures = 0
    private lastSuccessfulPollAt = Date.now()
    private readonly pollIntervalMs: number
    private readonly maxPollIntervalMs: number
    private readonly healthTimeoutMs: number
    private readonly internalFetchService: InternalFetchService

    constructor(private config: PluginsServerConfig) {
        this.pollIntervalMs = config.HOGFLOW_SCHEDULER_POLL_INTERVAL_MS
        this.maxPollIntervalMs = config.HOGFLOW_SCHEDULER_MAX_POLL_INTERVAL_MS
        this.healthTimeoutMs = config.HOGFLOW_SCHEDULER_HEALTH_TIMEOUT_MS
        this.internalFetchService = new InternalFetchService(config.INTERNAL_API_BASE_URL, config.INTERNAL_API_SECRET)
    }

    async start(): Promise<void> {
        if (this.running) {
            return
        }

        logger.info('HogFlowScheduleService: starting...')
        this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)
        logger.info('HogFlowScheduleService: Kafka producer connected')

        this.running = true
        this.pollPromise = this.pollLoop()
        logger.info('HogFlowScheduleService: started, polling every ' + this.pollIntervalMs + 'ms')
    }

    private nextSleepMs(): number {
        if (this.consecutiveFailures === 0) {
            return this.pollIntervalMs
        }
        return Math.min(this.pollIntervalMs * 2 ** this.consecutiveFailures, this.maxPollIntervalMs)
    }

    private async pollLoop(): Promise<void> {
        while (this.running) {
            const success = await this.pollAndDispatch()
            if (success) {
                this.consecutiveFailures = 0
                this.lastSuccessfulPollAt = Date.now()
            } else {
                this.consecutiveFailures++
            }
            if (this.running) {
                const sleepMs = this.nextSleepMs()
                await new Promise<void>((resolve) => {
                    this.sleepResolve = resolve
                    setTimeout(resolve, sleepMs)
                })
                this.sleepResolve = null
            }
        }
    }

    async pollAndDispatch(): Promise<boolean> {
        const startTime = Date.now()
        try {
            const { fetchResponse, fetchError } = await this.internalFetchService.fetch({
                urlPath: '/api/internal/hog_flows/process_due_schedules',
                fetchParams: {
                    method: 'POST',
                },
            })

            if (fetchError || !fetchResponse) {
                logger.error('HogFlowScheduleService: failed to call Django endpoint', {
                    error: String(fetchError),
                })
                schedulerPollCounter.inc({ status: 'error' })
                schedulerFailedCounter.inc({ stage: 'fetch' })
                return false
            }

            if (fetchResponse.status !== 200) {
                const errorText = await fetchResponse.text()
                logger.error('HogFlowScheduleService: Django endpoint returned error', {
                    status: fetchResponse.status,
                    error: errorText,
                })
                schedulerPollCounter.inc({ status: 'error' })
                schedulerFailedCounter.inc({ stage: 'django' })
                return false
            }

            const data = ProcessDueSchedulesResponseSchema.parse(parseJSON(await fetchResponse.text()))

            if (data.initialized.length > 0) {
                schedulerInitializedCounter.inc(data.initialized.length)
                logger.info('HogFlowScheduleService: initialized schedules', {
                    count: data.initialized.length,
                    scheduleIds: data.initialized,
                })
            }

            if (data.failed.length > 0) {
                schedulerFailedCounter.inc({ stage: 'process' }, data.failed.length)
                logger.error('HogFlowScheduleService: schedules failed to process', {
                    count: data.failed.length,
                    scheduleIds: data.failed,
                })
            }

            const results = await Promise.allSettled(
                data.processed.map((schedule) => this.dispatchBatchTrigger(schedule))
            )

            const failures = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected')
            const dispatched = data.processed.length - failures.length

            if (failures.length > 0) {
                const failedIds = data.processed
                    .filter((_, i) => results[i].status === 'rejected')
                    .map((s) => s.schedule_id)
                schedulerFailedCounter.inc({ stage: 'dispatch' }, failures.length)
                logger.error('HogFlowScheduleService: failed to dispatch some schedules', {
                    failedCount: failures.length,
                    totalCount: data.processed.length,
                    scheduleIds: failedIds,
                })
            }

            if (data.processed.length > 0) {
                const dispatchedIds = data.processed
                    .filter((_, i) => results[i].status === 'fulfilled')
                    .map((s) => s.schedule_id)
                schedulerDispatchedCounter.inc(dispatched)
                logger.info('HogFlowScheduleService: processed due schedules', {
                    count: data.processed.length,
                    dispatched: dispatchedIds.length,
                    scheduleIds: dispatchedIds,
                })
            }

            schedulerPollCounter.inc({ status: 'success' })
            return true
        } catch (err) {
            logger.error('HogFlowScheduleService: failed to poll', { error: String(err) })
            schedulerPollCounter.inc({ status: 'error' })
            schedulerFailedCounter.inc({ stage: 'poll' })
            return false
        } finally {
            schedulerPollDurationGauge.set(Date.now() - startTime)
        }
    }

    private async dispatchBatchTrigger(schedule: ProcessedSchedule): Promise<void> {
        if (!this.kafkaProducer) {
            throw new Error('Kafka producer not available')
        }

        const batchHogFlowRequest = {
            teamId: schedule.team_id,
            hogFlowId: schedule.hog_flow_id,
            parentRunId: null,
            filters: {
                properties: (schedule.filters?.properties as unknown[]) || [],
                filter_test_accounts: (schedule.filters?.filter_test_accounts as boolean) ?? false,
            },
            variables: schedule.variables,
        }

        await this.kafkaProducer.produce({
            topic: KAFKA_CDP_BATCH_HOGFLOW_REQUESTS,
            value: Buffer.from(JSON.stringify(batchHogFlowRequest)),
            key: `${schedule.team_id}_${schedule.hog_flow_id}`,
        })

        logger.info('HogFlowScheduleService: dispatched batch trigger', {
            scheduleId: schedule.schedule_id,
            hogFlowId: schedule.hog_flow_id,
            teamId: schedule.team_id,
        })
    }

    async stop(): Promise<void> {
        this.running = false
        this.sleepResolve?.()
        await this.pollPromise
        await this.kafkaProducer?.disconnect()
    }

    isHealthy(): HealthCheckResult {
        if (!this.running) {
            return new HealthCheckResultError('HogFlowScheduleService is not running', {})
        }
        if (Date.now() - this.lastSuccessfulPollAt > this.healthTimeoutMs) {
            return new HealthCheckResultError('HogFlowScheduleService has not polled successfully recently', {
                lastSuccessfulPollAt: new Date(this.lastSuccessfulPollAt).toISOString(),
                consecutiveFailures: this.consecutiveFailures,
            })
        }
        return new HealthCheckResultOk()
    }

    get service(): PluginServerService {
        return {
            id: 'cdp-hogflow-scheduler',
            onShutdown: () => this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }
}
