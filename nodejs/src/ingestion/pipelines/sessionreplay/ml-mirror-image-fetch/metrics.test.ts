import { register } from 'prom-client'

import { ImageFetchConsumerMetrics, ImageFetchRequestMetrics } from './metrics'

describe('image fetch metrics', () => {
    beforeEach(() => register.resetMetrics())
    afterEach(() => jest.restoreAllMocks())

    test.each([
        [undefined, 'network_error'],
        [199, 'other'],
        [200, '2xx'],
        [299, '2xx'],
        [300, '3xx'],
        [399, '3xx'],
        [400, '4xx'],
        [499, '4xx'],
        [500, '5xx'],
        [599, '5xx'],
        [600, 'other'],
    ] as const)('maps HTTP status %s to the bounded %s outcome', (status, expected) => {
        expect(ImageFetchRequestMetrics.outcomeForHttpStatus(status)).toBe(expected)
    })

    it('records retry causes with fixed semantic labels', async () => {
        ImageFetchRequestMetrics.incRetryCause('rate_limited')
        ImageFetchRequestMetrics.incRetryCause('server_error')
        ImageFetchRequestMetrics.incRetryCause('timeout')
        ImageFetchRequestMetrics.incRetryCause('error')

        const metric = (await register.getMetricsAsJSON()).find(
            (candidate) => candidate.name === 'ml_image_fetch_retry_causes_total'
        )
        const causes = metric?.values.map((value) => value.labels.cause)

        expect(causes).toEqual(['rate_limited', 'server_error', 'timeout', 'error'])
    })

    it('records bounded concentration and effective-count distributions', async () => {
        ImageFetchConsumerMetrics.observeBatchDiversity([6, 3, 1], [9, 1])

        const metrics = await register.getMetricsAsJSON()
        const topShare = metrics.find((metric) => metric.name === 'ml_image_fetch_batch_top_share')
        const effectiveCount = metrics.find((metric) => metric.name === 'ml_image_fetch_batch_effective_count')
        const topShareSums = topShare?.values.filter(
            (value) => 'metricName' in value && String(value.metricName).endsWith('_sum')
        )
        const effectiveCountSums = effectiveCount?.values.filter(
            (value) => 'metricName' in value && String(value.metricName).endsWith('_sum')
        )

        expect(topShareSums).toEqual([
            expect.objectContaining({ labels: { scope: 'origin', top_n: '1' }, value: 0.6 }),
            expect.objectContaining({ labels: { scope: 'origin', top_n: '5' }, value: 1 }),
            expect.objectContaining({ labels: { scope: 'origin', top_n: '10' }, value: 1 }),
            expect.objectContaining({ labels: { scope: 'registrable_domain', top_n: '1' }, value: 0.9 }),
            expect.objectContaining({ labels: { scope: 'registrable_domain', top_n: '5' }, value: 1 }),
            expect.objectContaining({ labels: { scope: 'registrable_domain', top_n: '10' }, value: 1 }),
        ])
        expect(effectiveCountSums).toEqual([
            expect.objectContaining({ labels: { scope: 'origin' }, value: 100 / 46 }),
            expect.objectContaining({ labels: { scope: 'registrable_domain' }, value: 100 / 82 }),
        ])
    })

    it('records partition flow, outcomes, waits, and concentration with bounded labels', async () => {
        ImageFetchConsumerMetrics.observePartitionRecord(7, 10, 9)
        ImageFetchConsumerMetrics.incPartitionUrls(7, 'unique', 8)
        ImageFetchConsumerMetrics.observePartitionBatchDiversity(7, [6, 2], [7, 1])
        ImageFetchRequestMetrics.observeRequest('2xx', 0.25, [7, 42])
        ImageFetchRequestMetrics.observeSchedulerWait('origin_crawl_delay', 1.5, [7, 42])
        ImageFetchRequestMetrics.incPartitionAttempt(7, 'completed', 'ok')
        ImageFetchRequestMetrics.incPartitionAttempt(7, 'republished', 'backoff')

        const metrics = await register.getMetricsAsJSON()
        const records = metrics.find((metric) => metric.name === 'ml_image_fetch_partition_records_total')
        const urls = metrics.find((metric) => metric.name === 'ml_image_fetch_partition_urls_total')
        const requests = metrics.find((metric) => metric.name === 'ml_image_fetch_partition_requests_total')
        const waits = metrics.find((metric) => metric.name === 'ml_image_fetch_partition_scheduler_wait_seconds')
        const attempts = metrics.find((metric) => metric.name === 'ml_image_fetch_partition_attempts_total')
        const topShare = metrics.find((metric) => metric.name === 'ml_image_fetch_partition_top_share')
        const effectiveCount = metrics.find((metric) => metric.name === 'ml_image_fetch_partition_effective_count')

        expect(records?.values).toContainEqual(expect.objectContaining({ labels: { partition: '7' }, value: 1 }))
        expect(urls?.values).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ labels: { partition: '7', stage: 'parsed' }, value: 10 }),
                expect.objectContaining({ labels: { partition: '7', stage: 'accepted' }, value: 9 }),
                expect.objectContaining({ labels: { partition: '7', stage: 'unique' }, value: 8 }),
            ])
        )
        expect(requests?.values).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ labels: { partition: '7', outcome: '2xx' }, value: 1 }),
                expect.objectContaining({ labels: { partition: '42', outcome: '2xx' }, value: 1 }),
            ])
        )
        expect(waits?.values).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ labels: { partition: '7', scope: 'origin_crawl_delay' }, value: 1 }),
                expect.objectContaining({ labels: { partition: '42', scope: 'origin_crawl_delay' }, value: 1 }),
            ])
        )
        expect(attempts?.values).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    labels: { partition: '7', disposition: 'completed', outcome: 'ok' },
                    value: 1,
                }),
                expect.objectContaining({
                    labels: { partition: '7', disposition: 'republished', outcome: 'backoff' },
                    value: 1,
                }),
            ])
        )
        expect(topShare?.values).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    metricName: expect.stringMatching(/_sum$/),
                    labels: { partition: '7', scope: 'origin' },
                    value: 0.75,
                }),
                expect.objectContaining({
                    metricName: expect.stringMatching(/_sum$/),
                    labels: { partition: '7', scope: 'registrable_domain' },
                    value: 0.875,
                }),
            ])
        )
        expect(effectiveCount?.values).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    metricName: expect.stringMatching(/_sum$/),
                    labels: { partition: '7', scope: 'origin' },
                    value: 64 / 40,
                }),
                expect.objectContaining({
                    metricName: expect.stringMatching(/_sum$/),
                    labels: { partition: '7', scope: 'registrable_domain' },
                    value: 64 / 50,
                }),
            ])
        )
    })

    it('records initial schedulable slots against the pod request limit', async () => {
        ImageFetchRequestMetrics.observeBatchSchedulableCapacity(7, 10)

        const metrics = await register.getMetricsAsJSON()
        const slots = metrics.find((metric) => metric.name === 'ml_image_fetch_batch_schedulable_slots')
        const ratio = metrics.find((metric) => metric.name === 'ml_image_fetch_batch_schedulable_capacity_ratio')

        expect(slots?.values).toContainEqual(
            expect.objectContaining({ metricName: expect.stringMatching(/_sum$/), value: 7 })
        )
        expect(ratio?.values).toContainEqual(
            expect.objectContaining({ metricName: expect.stringMatching(/_sum$/), value: 0.7 })
        )
    })

    it('keeps the oldest active batch age when another batch finishes', async () => {
        jest.spyOn(performance, 'now').mockReturnValue(3_000)
        const firstBatchId = ImageFetchConsumerMetrics.startBatch(1_000)
        const secondBatchId = ImageFetchConsumerMetrics.startBatch(2_000)

        ImageFetchConsumerMetrics.finishBatch(secondBatchId)
        const activeMetric = (await register.getMetricsAsJSON()).find(
            (metric) => metric.name === 'ml_image_fetch_consumer_active_batch_elapsed_seconds'
        )
        expect(activeMetric?.values[0].value).toBe(2)

        ImageFetchConsumerMetrics.finishBatch(firstBatchId)
        const idleMetric = (await register.getMetricsAsJSON()).find(
            (metric) => metric.name === 'ml_image_fetch_consumer_active_batch_elapsed_seconds'
        )
        expect(idleMetric?.values[0].value).toBe(0)
    })
})
