import { Message } from 'node-rdkafka'

import { KafkaConsumerInterface, RdKafkaConsumerConfig, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { insertIntakeBatch } from '../intake/intake-batch'
import { RunKind } from '../intake/message'
import { CDP_INTAKE_DLQ_OUTPUT } from '../outputs/outputs'
import { CyclotronV2Manager } from '../services/cyclotron-v2'
import { CdpDeadLetterService } from '../services/dead-letter/cdp-dead-letter.service'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'

// Bounded so that a Postgres outage stalls the partition and restarts the pod, which redelivers the batch. The pool
// bounds each attempt too, because the retry checks its time only after an attempt fails.
const CLAIM_RETRY = { initialDelayMs: 250, maxElapsedMs: 20_000 }
const ATTEMPT_TIMEOUT_MS = 5_000

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

/**
 * Inserts the runs that the send and webhook routes accepted onto one intake topic as cyclotron jobs.
 *
 * One deployment runs per topic, so a backlog of webhook runs never delays transactional sends.
 */
export class CdpIntakeConsumer extends CdpConsumerBase {
    protected name = 'CdpIntakeConsumer'
    private kafkaConsumer: KafkaConsumerInterface
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
        // Set rather than inherited from KAFKA_CONSUMER_AUTO_OFFSET_RESET, because a new group on `latest` would skip
        // every accepted run produced before its first assignment.
        this.kafkaConsumer = createKafkaConsumer({ groupId, topic: config[topicKey] }, {
            'auto.offset.reset': 'earliest',
        } as RdKafkaConsumerConfig)
        if (!config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CdpIntakeConsumer needs CYCLOTRON_NODE_DATABASE_URL to insert jobs')
        }
        this.cyclotron = new CyclotronV2Manager({
            pool: {
                dbUrl: config.CYCLOTRON_NODE_DATABASE_URL,
                statementTimeoutMs: ATTEMPT_TIMEOUT_MS,
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

    public async processBatch(messages: Message[]): Promise<void> {
        await insertIntakeBatch(
            messages,
            {
                cyclotron: this.cyclotron,
                deadLetters: this.deadLetters,
                invocationResults: this.invocationResultsService.invocationResultsRowsService,
                emailStatus: this.invocationResultsService.emailStatusService,
            },
            { kind: this.kind, claimRetry: CLAIM_RETRY }
        )
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
    }

    public override async stop(): Promise<void> {
        await this.kafkaConsumer.disconnect()
        await this.cyclotron.disconnect()
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
