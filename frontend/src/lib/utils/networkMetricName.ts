import { liveEventsHostOrigin } from './apiHost'

const NETWORK_METRIC_NAME = 'http.client.request.duration'

/**
 * Names the `metrics.network` histogram, skipping requests to the livestream service. Its
 * endpoints (`/notifications`, `/events`) are server-sent event streams that send headers only on
 * their first write, so a stream the app closes before then rejects with no content type the SDK
 * could skip it by. Its duration measures the subscription, not a request, and pins the
 * percentiles to the top bucket.
 */
export function networkMetricName(request: { url: string }): string | null {
    const liveOrigin = liveEventsHostOrigin()
    if (liveOrigin && request.url.startsWith(`${liveOrigin}/`)) {
        return null
    }
    return NETWORK_METRIC_NAME
}
