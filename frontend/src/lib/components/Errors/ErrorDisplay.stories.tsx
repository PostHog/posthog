import { Meta } from '@storybook/react'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'

import { EventType } from '~/types'

const meta: Meta<typeof ErrorDisplay> = {
    title: 'Components/Errors/Error Display',
    component: ErrorDisplay,
}
export default meta

function errorProperties(properties: Record<string, any>): EventType['properties'] {
    return {
        $os: 'Windows',
        $os_version: '10.0',
        $browser: 'Chrome',
        $device_type: 'Desktop',
        $current_url: 'https://app.posthog.com/home',
        $host: 'app.posthog.com',
        $pathname: '/home',
        $browser_version: 113,
        $browser_language: 'es-ES',
        $screen_height: 1080,
        $screen_width: 1920,
        $viewport_height: 929,
        $viewport_width: 1920,
        $lib: 'web',
        $lib_version: '1.63.3',
        distinct_id: 'iOizUPH4RH65nZjvGVBz5zZUmwdHvq2mxzNySQqqYkG',
        $device_id: '186144e7357245-0cfe8bf1b5b877-26021051-1fa400-186144e7358d3',
        $active_feature_flags: ['are-the-flags', 'important-for-the-error'],
        $feature_flag_payloads: {
            'are-the-flags': '{\n    "flag": "payload"\n}',
        },
        $user_id: 'iOizUPH4RH65nZjvGVBz5zZUmwdHvq2mxzNySQqqYkG',
        $groups: {
            project: '00000000-0000-0000-1847-88f0ffa23444',
            organization: '00000000-0000-0000-a050-5d4557279956',
            customer: 'the-customer',
            instance: 'https://app.posthog.com',
        },
        $exception_message: 'ResizeObserver loop limit exceeded',
        $exception_type: 'Error',
        $exception_fingerprint: 'Error',
        $exception_personURL: 'https://app.posthog.com/person/the-person-id',
        $sentry_event_id: 'id-from-the-sentry-integration',
        $sentry_exception: {
            values: [
                {
                    value: 'ResizeObserver loop limit exceeded',
                    type: 'Error',
                    mechanism: {
                        type: 'onerror',
                        handled: false,
                        synthetic: true,
                    },
                    stacktrace: {
                        frames: [
                            {
                                colno: 0,
                                filename: 'https://app.posthog.com/home',
                                function: '?',
                                in_app: true,
                                lineno: 0,
                            },
                        ],
                    },
                },
            ],
        },
        $sentry_exception_message: 'ResizeObserver loop limit exceeded',
        $sentry_exception_type: 'Error',
        $sentry_tags: {
            'PostHog Person URL': 'https://app.posthog.com/person/the-person-id',
            'PostHog Recording URL': 'https://app.posthog.com/replay/the-session-id?t=866',
        },
        $sentry_url:
            'https://sentry.io/organizations/posthog/issues/?project=the-sentry-project-id&query=the-sentry-id',
        $session_id: 'the-session-id',
        $window_id: 'the-window-id',
        $pageview_id: 'the-pageview-id',
        $sent_at: '2023-06-03T10:03:57.787000+00:00',
        $geoip_city_name: 'Whoville',
        $geoip_country_name: 'Wholand',
        $geoip_country_code: 'WH',
        $geoip_continent_name: 'Mystery',
        $geoip_continent_code: 'MY',
        $geoip_latitude: -30.5023,
        $geoip_longitude: -71.1545,
        $geoip_time_zone: 'UTC',
        $lib_version__major: 1,
        $lib_version__minor: 63,
        $lib_version__patch: 3,
        ...properties,
    }
}

export function ResizeObserverLoopLimitExceeded(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_message: 'ResizeObserver loop limit exceeded',
                $exception_type: 'Error',
                $exception_personURL: 'https://app.posthog.com/person/the-person-id',
            })}
        />
    )
}

export function SafariScriptError(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_type: 'Error',
                $exception_message: 'Script error.',
                $exception_is_synthetic: true,
            })}
        />
    )
}

export function ImportingModule(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_type: 'UnhandledRejection',
                $exception_message: "Importing module '/static/chunk-PIJHGO7Q.js' is not found.",
                $exception_stack_trace_raw: '[]',
                $exception_handled: false,
            })}
        />
    )
}

export function AnonymousErrorWithStackTrace(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_type: 'Error',
                $exception_message: 'wat',
                $exception_stack_trace_raw:
                    '[{"filename":"<anonymous>","function":"?","in_app":true,"lineno":1,"colno":26}]',
            })}
        />
    )
}
