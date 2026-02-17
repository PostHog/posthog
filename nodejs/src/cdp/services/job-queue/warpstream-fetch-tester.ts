import { Message } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import { getKafkaConfigFromEnv } from '../../../kafka/config'
import { PluginsServerConfig } from '../../../types'
import { logger } from '../../../utils/logger'
import { fetch } from '../../../utils/request'

export const cdpSeekLatencyMs = new Histogram({
    name: 'cdp_seek_latency_ms',
    help: 'Latency in ms of fetching a record from WarpStream via HTTP',
    buckets: [1, 5, 10, 25, 50, 100, 150, 200, 250, 500, 1000, 2500, 5000, 10000],
})

export const cdpSeekResult = new Counter({
    name: 'cdp_seek_result_total',
    help: 'Count of fetch test results by outcome',
    labelNames: ['result'],
})

export class WarpstreamFetchTester {
    private authHeader?: string

    constructor(private config: PluginsServerConfig) {}

    start(): void {
        const kafkaConfig = getKafkaConfigFromEnv('CONSUMER')
        const username = kafkaConfig['sasl.username'] as string | undefined
        const password = kafkaConfig['sasl.password'] as string | undefined

        if (username && password) {
            this.authHeader = 'Basic ' + Buffer.from(`${username}:${password}`).toString('base64')
        }
    }

    async maybeMeasureFetchLatency(message: Message): Promise<void> {
        if (Math.random() >= this.config.CDP_CYCLOTRON_TEST_SEEK_SAMPLE_RATE) {
            return
        }

        const { topic, partition, offset } = message
        const maxSeekBack = Math.min(this.config.CDP_CYCLOTRON_TEST_SEEK_MAX_OFFSET, offset)
        if (maxSeekBack <= 0) {
            return
        }

        const seekBack = Math.floor(Math.random() * maxSeekBack) + 1
        const targetOffset = offset - seekBack
        const url = `${this.config.CDP_CYCLOTRON_WARPSTREAM_HTTP_URL}/v1/kafka/topics/${topic}/partitions/${partition}/records/${targetOffset}`

        try {
            const headers: Record<string, string> = {}
            if (this.authHeader) {
                headers['Authorization'] = this.authHeader
            }

            const start = performance.now()
            const response = await fetch(url, { headers })
            const latencyMs = performance.now() - start

            cdpSeekLatencyMs.observe(latencyMs)

            if (response.status >= 200 && response.status < 300) {
                cdpSeekResult.labels({ result: 'success' }).inc()
                logger.info('seek_test', {
                    latencyMs: Math.round(latencyMs * 100) / 100,
                    partition,
                    currentOffset: offset,
                    targetOffset,
                    seekBack,
                    status: response.status,
                })
            } else {
                cdpSeekResult.labels({ result: 'error' }).inc()
                logger.warn('seek_test_error', {
                    status: response.status,
                    url,
                    partition,
                })
            }

            await response.dump()
        } catch (error) {
            cdpSeekResult.labels({ result: 'error' }).inc()
            logger.warn('seek_test_error', { error: String(error), topic, partition })
        }
    }
}
