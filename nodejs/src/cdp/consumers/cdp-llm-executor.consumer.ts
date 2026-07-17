import { Message } from 'node-rdkafka'
import { Pool } from 'pg'
import { Counter } from 'prom-client'

import { KAFKA_CDP_LLM_REQUESTS } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { LlmBlobStore, buildLlmBlobStore } from '../services/llm/llm-blob-store'
import { executeLlmRequest } from '../services/llm/llm-executor-core'
import { FetchLlmGatewayClient, LlmGatewayClient } from '../services/llm/llm-gateway.client'
import { LlmStepRequest } from '../services/llm/llm-step.types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

const counterLlmRequestsReceived = new Counter({
    name: 'cdp_llm_executor_requests_received',
    help: 'LLM step requests the executor pulled off the dispatch topic.',
})

const counterLlmWakeOutcome = new Counter({
    name: 'cdp_llm_executor_wake_outcome',
    help: 'Outcome of the wake write after an LLM call. `missed` means the timeout won the race.',
    labelNames: ['outcome'],
})

const counterLlmExecutorErrors = new Counter({
    name: 'cdp_llm_executor_errors',
    help: 'LLM requests the executor could not process at all (both the call and the error-wake failed).',
})

// Consumes LLM step requests, calls the LLM gateway (holding the connection for the whole call),
// and wakes the parked cyclotron job by id with the completion or a terminal error. Deployed as its
// own fleet - I/O-bound, isolated from the workflow workers, scaled by in-flight concurrency.
export class CdpLlmExecutorConsumer<
    TConfig extends PluginsServerConfig = PluginsServerConfig,
> extends CdpConsumerBase<TConfig> {
    protected name = 'CdpLlmExecutorConsumer'
    protected kafkaConsumer: KafkaConsumerInterface
    private cyclotronPool: Pool
    private gatewayClient: LlmGatewayClient
    private blobStore: LlmBlobStore | null

    constructor(config: TConfig, deps: CdpConsumerBaseDeps, gatewayClient?: LlmGatewayClient) {
        super(config, deps)
        this.blobStore = buildLlmBlobStore()
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-llm-executor-consumer',
            topic: KAFKA_CDP_LLM_REQUESTS,
        })

        if (!config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CdpLlmExecutorConsumer requires CYCLOTRON_NODE_DATABASE_URL to wake parked jobs')
        }
        this.cyclotronPool = new Pool({
            connectionString: config.CYCLOTRON_NODE_DATABASE_URL,
            max: config.CYCLOTRON_NODE_MAX_CONNECTIONS,
        })

        this.gatewayClient = gatewayClient ?? buildDefaultGatewayClient()
    }

    public async processBatch(requests: LlmStepRequest[]): Promise<void> {
        if (!requests.length) {
            return
        }
        // Each request is independent async I/O; a batch runs concurrently. Per-request failures are
        // swallowed (and covered by the parked job's timeout backstop) so one bad request can't stall
        // the offset for the rest of the batch.
        await Promise.all(requests.map((request) => this.processRequest(request)))
    }

    private async processRequest(request: LlmStepRequest): Promise<void> {
        counterLlmRequestsReceived.inc()
        try {
            const { outcome } = await executeLlmRequest({
                request,
                gatewayClient: this.gatewayClient,
                pool: this.cyclotronPool,
                blobStore: this.blobStore ?? undefined,
            })
            counterLlmWakeOutcome.labels({ outcome }).inc()
        } catch (err) {
            counterLlmExecutorErrors.inc()
            logger.error('LLM executor failed to process request', { jobId: request.jobId, err })
        }
    }

    private parseBatch(messages: Message[]): LlmStepRequest[] {
        const requests: LlmStepRequest[] = []
        for (const message of messages) {
            if (!message.value) {
                continue
            }
            try {
                requests.push(parseJSON(message.value.toString()) as LlmStepRequest)
            } catch (err: any) {
                counterParseError.labels({ error: err.message }).inc()
                logger.error('Failed to parse LLM request message', { err })
            }
        }
        return requests
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn('cdpLlmExecutor.handleEachBatch', async () => {
                return { backgroundTask: this.processBatch(this.parseBatch(messages)) }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.kafkaConsumer.disconnect()
        await this.cyclotronPool.end()
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

function buildDefaultGatewayClient(): LlmGatewayClient {
    const baseUrl = process.env.CDP_LLM_GATEWAY_URL ?? ''
    if (!baseUrl) {
        logger.warn('⚠️', 'CDP_LLM_GATEWAY_URL is not set - LLM steps will fail and fall back to their timeout branch')
    }
    // MVP: a single configured token. The real gateway resolves per-team project API keys; that
    // credential resolution is a follow-up (see the RFC's auth section).
    const token = process.env.CDP_LLM_GATEWAY_TOKEN ?? ''
    // Default 5 min - matches the current gateway request cap. Reasoning models need a higher
    // per-model override; the parked job's max_wait_duration is the outer backstop regardless.
    const requestTimeoutMs = Number(process.env.CDP_LLM_GATEWAY_REQUEST_TIMEOUT_MS ?? 300_000)
    return new FetchLlmGatewayClient({
        baseUrl,
        resolveAuthToken: () => token,
        requestTimeoutMs,
    })
}
