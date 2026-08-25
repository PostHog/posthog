import { register } from 'prom-client'

import { ImageFetchConsumerMetrics, ImageFetchRequestMetrics } from './metrics'

describe('image fetch metrics', () => {
    beforeEach(() => register.resetMetrics())

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
})
