import { getExceptionPropertiesFrom } from 'lib/components/Errors/ErrorDisplay'

describe('Error Display', () => {
    it('can read sentry stack trace when $exception_stack_trace_raw is not present', () => {
        const eventProperties = {
            'should not be in the': 'result',
            $browser: 'Chrome',
            $browser_version: '92.0.4515',
            $active_feature_flags: ['feature1,feature2'],
            $lib: 'posthog-js',
            $lib_version: '1.0.0',
            $os: 'Windows',
            $os_version: '10',
            $sentry_exception_message: 'There was an error creating the support ticket with zendesk.',
            $exception_message: 'There was an error creating the support ticket with zendesk.',
            $sentry_tags: {
                'PostHog Person URL': 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
                'PostHog Recording URL': 'https://app.posthog.com/replay/018dc30d-a8a5-7257-9faf-dcd97c0e19cf?t=2294',
            },
            $sentry_exception: {
                values: [
                    {
                        mechanism: {
                            handled: true,
                            type: 'generic',
                        },
                        stacktrace: {
                            frames: [
                                {
                                    colno: 220,
                                    filename: 'https://app-static-prod.posthog.com/static/chunk-UFQKIDIH.js',
                                    function: 'submitZendeskTicket',
                                    in_app: true,
                                    lineno: 25,
                                },
                            ],
                        },
                        type: 'Error',
                        value: 'There was an error creating the support ticket with zendesk.',
                    },
                ],
            },
            $sentry_url:
                'https://sentry.io/organizations/posthog/issues/?project=1899813&query=40e442d79c22473391aeeeba54c82163',
            $sentry_event_id: '40e442d79c22473391aeeeba54c82163',
            $sentry_exception_type: 'Error',
            $exception_personURL: 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
            $exception_type: 'Error',
        }
        const result = getExceptionPropertiesFrom(eventProperties)
        expect(result).toEqual({
            $active_feature_flags: ['feature1,feature2'],
            $browser: 'Chrome',
            $browser_version: '92.0.4515',
            $exception_message: 'There was an error creating the support ticket with zendesk.',
            $exception_stack_trace_raw:
                '[{"colno":220,"filename":"https://app-static-prod.posthog.com/static/chunk-UFQKIDIH.js","function":"submitZendeskTicket","in_app":true,"lineno":25}]',
            $exception_list: [
                {
                    mechanism: {
                        handled: true,
                        type: 'generic',
                    },
                    stacktrace: {
                        frames: [
                            {
                                colno: 220,
                                filename: 'https://app-static-prod.posthog.com/static/chunk-UFQKIDIH.js',
                                function: 'submitZendeskTicket',
                                in_app: true,
                                lineno: 25,
                            },
                        ],
                    },
                    type: 'Error',
                    value: 'There was an error creating the support ticket with zendesk.',
                },
            ],
            $exception_synthetic: undefined,
            $exception_type: 'Error',
            $lib: 'posthog-js',
            $lib_version: '1.0.0',
            $level: undefined,
            $os: 'Windows',
            $os_version: '10',
            $sentry_url:
                'https://sentry.io/organizations/posthog/issues/?project=1899813&query=40e442d79c22473391aeeeba54c82163',
        })
    })

    it('can read sentry message', () => {
        const eventProperties = {
            'should not be in the': 'result',
            $browser: 'Chrome',
            $browser_version: '92.0.4515',
            $active_feature_flags: ['feature1,feature2'],
            $lib: 'posthog-js',
            $lib_version: '1.0.0',
            $os: 'Windows',
            $os_version: '10',
            $sentry_tags: {
                'PostHog Person URL': 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
                'PostHog Recording URL': 'https://app.posthog.com/replay/018dc30d-a8a5-7257-9faf-dcd97c0e19cf?t=2294',
            },
            $sentry_exception: undefined,
            $sentry_url:
                'https://sentry.io/organizations/posthog/issues/?project=1899813&query=40e442d79c22473391aeeeba54c82163',
            $sentry_event_id: '40e442d79c22473391aeeeba54c82163',
            $sentry_exception_type: undefined,
            $exception_personURL: 'https://app.posthog.com/person/f6kW3HXaha6dAvHZiOmgrcAXK09682P6nNPxvfjqM9c',
            $exception_type: undefined,
            $level: 'info',
            $exception_message: 'the message sent into sentry captureMessage',
        }
        const result = getExceptionPropertiesFrom(eventProperties)
        expect(result).toEqual({
            $active_feature_flags: ['feature1,feature2'],
            $browser: 'Chrome',
            $browser_version: '92.0.4515',
            $exception_message: 'the message sent into sentry captureMessage',
            $exception_stack_trace_raw: undefined,
            $exception_synthetic: undefined,
            $exception_type: undefined,
            $lib: 'posthog-js',
            $lib_version: '1.0.0',
            $level: 'info',
            $os: 'Windows',
            $os_version: '10',
            $sentry_url:
                'https://sentry.io/organizations/posthog/issues/?project=1899813&query=40e442d79c22473391aeeeba54c82163',
        })
    })
})
