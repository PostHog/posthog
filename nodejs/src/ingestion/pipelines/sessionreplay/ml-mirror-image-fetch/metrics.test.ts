import { register } from 'prom-client'

import { ImageFetchRequestMetrics } from './metrics'

describe('ImageFetchRequestMetrics', () => {
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
})
