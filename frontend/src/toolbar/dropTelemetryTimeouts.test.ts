import { dropTelemetryTimeouts } from './dropTelemetryTimeouts'

describe('dropTelemetryTimeouts', () => {
    it('drops the self-inflicted posthog-js telemetry timeout AbortError', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'AbortError', value: 'PostHog request timed out after 3000ms' }],
            },
        }
        expect(dropTelemetryTimeouts(event)).toBeNull()
    })

    it('passes through AbortErrors that are not the telemetry timeout', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [{ type: 'AbortError', value: 'The user aborted a request.' }],
            },
        }
        expect(dropTelemetryTimeouts(event)).toBe(event)
    })

    it('passes through other exceptions and non-exception events', () => {
        const exception = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
        }
        expect(dropTelemetryTimeouts(exception)).toBe(exception)

        const pageview = { event: '$pageview', properties: {} }
        expect(dropTelemetryTimeouts(pageview)).toBe(pageview)
    })

    it('tolerates missing properties and null (before_send contract)', () => {
        expect(dropTelemetryTimeouts({ event: '$exception' })).toEqual({ event: '$exception' })
        expect(dropTelemetryTimeouts(null)).toBeNull()
    })
})
