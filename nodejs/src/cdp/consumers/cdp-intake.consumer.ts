import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KafkaConsumerInterface, RdKafkaConsumerConfig, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { IntakeBatchServices, insertIntakeBatch } from '../intake/intake-batch'
import { RunKind } from '../intake/message'
import { CDP_INTAKE_DLQ_OUTPUT } from '../outputs/outputs'
import { CyclotronV2Manager } from '../services/cyclotron-v2'
import { CdpDeadLetterService } from '../services/dead-letter/cdp-dead-letter.service'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'

// Bounded so that a Postgres outage stalls the partition and restarts the pod, which redelivers the batch. The pool
// bounds each attempt too, because the retry checks its time only after an attempt fails.
const CLAIM_RETRY = { initialDelayMs: 250, maxElapsedMs: 20_000 }
const ATTEMPT_TIMEOUT_MS = 5_000

// A record that still fails while draining holds the drain on it instead of being parked on the topic it came from again.
const DRAIN_RETRY_MS = { initial: 1_000, max: 30_000 }
const drainStallsCounter = new Counter({
    name: 'cdp_intake_dlq_drain_stalls_total',
    help: 'Drain attempts on the intake dead-letter topic that failed and will retry the same records.',
    labelNames: ['kind'] as const,
})

const STALL_ON_FAILURE: IntakeBatchServices['deadLetters'] = {
    recordMessageFailure: () => false,
    produceForBatch: () => Promise.resolve(),
}

const TOPICS: Record<
    RunKind,
    { topicKey: 'CDP_INTAKE_TRANSACTIONAL_EMAIL_TOPIC' | 'CDP_INTAKE_WORKFLOW_WEBHOOK_TOPIC'; groupId: string }
> = {
    'transactional-email': {
        topicKey: 'CDP_INTAKE_TRANSACTIONAL_EMAIL_TOPIC',
        groupId: 'cdp-intake-transactional-email-consumer',
    },
    'workflow-webhook': {
        topicKey: 'CDP_INTAKE_WORKFLOW_WEBHOOK_TOPIC',
        groupId: 'cdp-intake-workflow-webhook-consumer',
    },
}

// One deployment runs per intake topic, so a backlog of webhook runs never delays transactional sends.
export class CdpIntakeConsumer extends CdpConsumerBase {
    protected name = 'CdpIntakeConsumer'
    private kafkaConsumer: KafkaConsumerInterface
    private drainConsumer?: KafkaConsumerInterface
    private groupId: string
    private stopping = false
    private cyclotron: CyclotronV2Manager
    private deadLetters: CdpDeadLetterService

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        private kind: RunKind
    ) {
        super(config, deps)
        const { topicKey, groupId } = TOPICS[kind]
        this.name = `CdpIntakeConsumer(${kind})`
        this.groupId = groupId
        // Set rather than inherited from KAFKA_CONSUMER_AUTO_OFFSET_RESET, because a new group on `latest` would skip
        // every accepted run produced before its first assignment.
        this.kafkaConsumer = createKafkaConsumer({ groupId, topic: config[topicKey] }, {
            'auto.offset.reset': 'earliest',
        } as RdKafkaConsumerConfig)
        if (config.CDP_INTAKE_DLQ_DRAIN) {
            // A held drain stops polling while it retries, so its group must not evict it for being slow.
            this.drainConsumer = createKafkaConsumer(
                { groupId: `${groupId}-dlq-drain`, topic: config.CDP_INTAKE_DLQ_TOPIC },
                { 'auto.offset.reset': 'earliest', 'max.poll.interval.ms': 86_400_000 } as RdKafkaConsumerConfig
            )
        }
        if (!config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CdpIntakeConsumer needs CYCLOTRON_NODE_DATABASE_URL to insert jobs')
        }
        this.cyclotron = new CyclotronV2Manager({
            pool: {
                dbUrl: config.CYCLOTRON_NODE_DATABASE_URL,
                connectionTimeoutMs: ATTEMPT_TIMEOUT_MS,
            },
            depthLimit: config.CYCLOTRON_SHARD_DEPTH_LIMIT,
        })
        this.deadLetters = new CdpDeadLetterService(config, {
            outputs: this.outputs,
            output: CDP_INTAKE_DLQ_OUTPUT,
            consumerGroup: groupId,
            parseFailuresStallBatch: true,
        })
    }

    public async processBatch(
        messages: Message[],
        deadLetters: IntakeBatchServices['deadLetters'] = this.deadLetters
    ): Promise<void> {
        await insertIntakeBatch(
            messages,
            {
                cyclotron: this.cyclotron,
                deadLetters,
                invocationResults: this.invocationResultsService.invocationResultsRowsService,
                emailStatus: this.invocationResultsService.emailStatusService,
            },
            { kind: this.kind, claimRetry: CLAIM_RETRY }
        )
    }

    // Both intake consumers park on one topic, so each drains only the records its own group parked.
    public async drainBatch(messages: Message[]): Promise<void> {
        const own = messages.filter((message) => headerOf(message, 'dlq_consumer_group') === this.groupId)
        await this.processBatch(own, STALL_ON_FAILURE)
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.deadLetters.checkTopic()
        await this.cyclotron.connect()
        // The batch is awaited inside the handler, so offsets are stored only after every write.
        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn(`cdpIntakeConsumer.${this.kind}.handleEachBatch`, async () => {
                await this.processBatch(messages)
                return { backgroundTask: Promise.resolve() }
            })
        })
        await this.drainConsumer?.connect(async (messages) => {
            return await instrumentFn(`cdpIntakeConsumer.${this.kind}.handleEachDrainBatch`, async () => {
                await this.drainUntilDone(messages)
                return { backgroundTask: Promise.resolve() }
            })
        })
    }

    // A throw from a batch handler stops the whole process, so a failing drain retries here and the intake topic keeps flowing.
    private async drainUntilDone(messages: Message[]): Promise<void> {
        for (let delayMs = DRAIN_RETRY_MS.initial; ; delayMs = Math.min(delayMs * 2, DRAIN_RETRY_MS.max)) {
            try {
                return await this.drainBatch(messages)
            } catch (error) {
                if (this.stopping) {
                    throw error
                }
                drainStallsCounter.labels({ kind: this.kind }).inc()
                logger.error('[CdpIntake] A dead letter still fails, so the drain holds and retries it', {
                    kind: this.kind,
                    delayMs,
                    error: error instanceof Error ? error.message : String(error),
                })
                await new Promise((resolve) => setTimeout(resolve, delayMs))
            }
        }
    }

    public override async stop(): Promise<void> {
        this.stopping = true
        await this.kafkaConsumer.disconnect()
        await this.drainConsumer?.disconnect()
        await this.cyclotron.disconnect()
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

function headerOf(message: Message, key: string): string | undefined {
    for (const header of message.headers ?? []) {
        const value = header[key]
        if (value !== undefined) {
            return value.toString()
        }
    }
    return undefined
}
