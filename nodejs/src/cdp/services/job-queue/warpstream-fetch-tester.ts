import { Message } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import { getKafkaConfigFromEnv } from '../../../kafka/config'
import { PluginsServerConfig } from '../../../types'
import { logger } from '../../../utils/logger'
import { fetch } from '../../../utils/request'

export const cdpSeekLatencyMs = new Histogram({
    name: 'cdp_seek_latency_ms',
    help: 'Latency in ms of a single individual fetch request to WarpStream via HTTP',
    buckets: [1, 5, 10, 25, 50, 100, 150, 200, 250, 500, 1000, 2500, 5000, 10000],
})

export const cdpSeekTotalLatencyMs = new Histogram({
    name: 'cdp_seek_total_latency_ms',
    help: 'Total wall-clock time in ms for all parallel individual fetch requests',
    buckets: [1, 5, 10, 25, 50, 100, 150, 200, 250, 500, 1000, 2500, 5000, 10000],
})

export const cdpSeekBatchLatencyMs = new Histogram({
    name: 'cdp_seek_batch_latency_ms',
    help: 'Latency in ms of a single batch fetch request to WarpStream via HTTP',
    buckets: [1, 5, 10, 25, 50, 100, 150, 200, 250, 500, 1000, 2500, 5000, 10000],
})

export const cdpSeekBatchTotalLatencyMs = new Histogram({
    name: 'cdp_seek_batch_total_latency_ms',
    help: 'Total wall-clock time in ms for all parallel batch fetch requests',
    buckets: [1, 5, 10, 25, 50, 100, 150, 200, 250, 500, 1000, 2500, 5000, 10000],
})

export const cdpSeekResult = new Counter({
    name: 'cdp_seek_result_total',
    help: 'Count of fetch test results by outcome and method',
    labelNames: ['result', 'method'],
})

type FetchTarget = {
    topic: string
    partition: number
    currentOffset: number
    targetOffset: number
    seekBack: number
}

export class WarpstreamFetchTester {
    private authHeader?: string

    constructor(private config: PluginsServerConfig) {}

    start(): void {
        if (!this.config.CDP_CYCLOTRON_WARPSTREAM_HTTP_URL) {
            throw new Error('CDP_CYCLOTRON_WARPSTREAM_HTTP_URL must be configured to use WarpstreamFetchTester')
        }

        const kafkaConfig = getKafkaConfigFromEnv('CONSUMER')
        const username = kafkaConfig['sasl.username'] as string | undefined
        const password = kafkaConfig['sasl.password'] as string | undefined

        if (username && password) {
            this.authHeader = 'Basic ' + Buffer.from(`${username}:${password}`).toString('base64')
        }
    }

    async maybeMeasureFetchLatency(messages: Message[]): Promise<void> {
        const allTargets = this.buildTargets(messages)
        if (allTargets.length === 0) {
            return
        }

        const individualCount = this.config.CDP_CYCLOTRON_TEST_FETCH_INDIVIDUAL_COUNT
        const batchCount = this.config.CDP_CYCLOTRON_TEST_FETCH_BATCH_COUNT
        const batchSize = this.config.CDP_CYCLOTRON_TEST_FETCH_BATCH_SIZE

        const tasks: Promise<void>[] = []

        if (individualCount > 0) {
            const targets = this.sampleTargets(allTargets, individualCount)
            tasks.push(this.runIndividualFetches(targets))
        }

        if (batchCount > 0 && batchSize > 0) {
            const targets = this.sampleTargets(allTargets, batchCount * batchSize)
            tasks.push(this.runBatchFetches(targets))
        }

        await Promise.all(tasks)
    }

    private async runIndividualFetches(targets: FetchTarget[]): Promise<void> {
        const totalStart = performance.now()

        await Promise.allSettled(
            targets.map(async (target) => {
                const url = `${this.config.CDP_CYCLOTRON_WARPSTREAM_HTTP_URL}/v1/kafka/topics/${target.topic}/partitions/${target.partition}/records/${target.targetOffset}`

                try {
                    const start = performance.now()
                    const response = await fetch(url, { headers: this.getHeaders() })
                    await response.text()
                    const latencyMs = performance.now() - start

                    cdpSeekLatencyMs.observe(latencyMs)

                    if (response.status >= 200 && response.status < 300) {
                        cdpSeekResult.labels({ result: 'success', method: 'individual' }).inc()
                    } else {
                        cdpSeekResult.labels({ result: 'error', method: 'individual' }).inc()
                        logger.warn('seek_test_individual_error', {
                            status: response.status,
                            partition: target.partition,
                        })
                    }
                } catch (error) {
                    cdpSeekResult.labels({ result: 'error', method: 'individual' }).inc()
                    logger.warn('seek_test_individual_error', { error: String(error) })
                }
            })
        )

        const totalLatencyMs = performance.now() - totalStart
        cdpSeekTotalLatencyMs.observe(totalLatencyMs)
        logger.info('seek_test_individual_complete', {
            latencyMs: Math.round(totalLatencyMs * 100) / 100,
            count: targets.length,
        })
    }

    private async runBatchFetches(targets: FetchTarget[]): Promise<void> {
        const batchSize = this.config.CDP_CYCLOTRON_TEST_FETCH_BATCH_SIZE
        const chunks: FetchTarget[][] = []
        for (let i = 0; i < targets.length; i += batchSize) {
            chunks.push(targets.slice(i, i + batchSize))
        }

        const totalStart = performance.now()

        await Promise.allSettled(
            chunks.map(async (chunk) => {
                const partitionsByTopic = new Map<string, { partition: number; fetch_offset: number }[]>()
                for (const target of chunk) {
                    const existing = partitionsByTopic.get(target.topic) ?? []
                    existing.push({ partition: target.partition, fetch_offset: target.targetOffset })
                    partitionsByTopic.set(target.topic, existing)
                }

                const body = {
                    topics: Array.from(partitionsByTopic.entries()).map(([topic, partitions]) => ({
                        topic,
                        partitions: partitions.map((p) => ({
                            partition: p.partition,
                            fetch_offset: p.fetch_offset,
                            partition_max_bytes: 1048576,
                        })),
                    })),
                }

                const url = `${this.config.CDP_CYCLOTRON_WARPSTREAM_HTTP_URL}/v1/kafka/fetch`

                try {
                    const headers = this.getHeaders()
                    headers['Content-Type'] = 'application/json'

                    const start = performance.now()
                    const response = await fetch(url, {
                        method: 'POST',
                        headers,
                        body: JSON.stringify(body),
                    })
                    await response.text()
                    const latencyMs = performance.now() - start

                    cdpSeekBatchLatencyMs.observe(latencyMs)

                    if (response.status >= 200 && response.status < 300) {
                        cdpSeekResult.labels({ result: 'success', method: 'batch' }).inc()
                    } else {
                        cdpSeekResult.labels({ result: 'error', method: 'batch' }).inc()
                        logger.warn('seek_test_batch_error', {
                            status: response.status,
                            recordCount: chunk.length,
                        })
                    }
                } catch (error) {
                    cdpSeekResult.labels({ result: 'error', method: 'batch' }).inc()
                    logger.warn('seek_test_batch_error', { error: String(error), recordCount: chunk.length })
                }
            })
        )

        const totalLatencyMs = performance.now() - totalStart
        cdpSeekBatchTotalLatencyMs.observe(totalLatencyMs)
        logger.info('seek_test_batch_complete', {
            latencyMs: Math.round(totalLatencyMs * 100) / 100,
            batchCount: chunks.length,
            batchSize,
            totalRecords: targets.length,
        })
    }

    private getHeaders(): Record<string, string> {
        const headers: Record<string, string> = {}
        if (this.authHeader) {
            headers['Authorization'] = this.authHeader
        }
        return headers
    }

    private sampleTargets(targets: FetchTarget[], count: number): FetchTarget[] {
        if (targets.length <= count) {
            return targets
        }
        const shuffled = [...targets]
        for (let i = shuffled.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1))
            ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
        }
        return shuffled.slice(0, count)
    }

    private buildTargets(messages: Message[]): FetchTarget[] {
        const targets: FetchTarget[] = []

        for (const message of messages) {
            const { topic, partition, offset } = message
            if (!topic) {
                continue
            }
            const maxSeekBack = Math.min(this.config.CDP_CYCLOTRON_TEST_SEEK_MAX_OFFSET, offset)
            if (maxSeekBack <= 0) {
                continue
            }

            const seekBack = Math.floor(Math.random() * maxSeekBack) + 1
            targets.push({
                topic,
                partition,
                currentOffset: offset,
                targetOffset: offset - seekBack,
                seekBack,
            })
        }

        return targets
    }
}
