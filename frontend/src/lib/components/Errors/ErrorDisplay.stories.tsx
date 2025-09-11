import { Meta } from '@storybook/react'

import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'

import { mswDecorator } from '~/mocks/browser'
import { EventType } from '~/types'

const meta: Meta<typeof ErrorDisplay> = {
    title: 'Components/Errors/Error Display',
    component: ErrorDisplay,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/error_tracking/stack_frames/': {
                    results: [
                        {
                            id: '123456789',
                            raw_id: 'rawId',
                            contents: {},
                            resolved: true,
                            context: {
                                before: [
                                    {
                                        number: 7,
                                        line: '    const displayFrames = showAllFrames ? frames : frames.filter((f) => f.in_app)',
                                    },
                                    {
                                        number: 8,
                                        line: '',
                                    },
                                    { number: 9, line: '    useEffect(() => {' },
                                ],
                                line: { number: 10, line: '        loadFrameContexts({ frames })' },
                                after: [
                                    { number: 11, line: '    }, [frames, loadFrameContexts])' },
                                    {
                                        number: 12,
                                        line: '',
                                    },
                                    {
                                        number: 13,
                                        line: '    const initiallyActiveIndex = displayFrames.findIndex((f) => f.in_app) || 0',
                                    },
                                ],
                            },
                            symbol_set_ref: 'https://static.posthog.com/chunks.js',
                        },
                    ],
                },
            },
        }),
    ],
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
        $exception_fingerprint: 'Error',
        $exception_personURL: 'https://app.posthog.com/person/the-person-id',
        $sentry_event_id: 'id-from-the-sentry-integration',
        $sentry_exception: {
            values: [
                {
                    value: "DB::Exception: There was an error on [localhost:9000]: Code: 701. DB::Exception: Requested cluster 'posthog_single_shard' not found. (CLUSTER_DOESNT_EXIST) (version 23.11.2.11 (official build)). Stack trace: 0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x000000000c4fd597 in /usr/bin/clickhouse 1. DB::DDLQueryStatusSource::generate() @ 0x00000000113205f8 in /usr/bin/clickhouse 2. DB::ISource::tryGenerate() @ 0x0000000012290275 in /usr/bin/clickhouse 3. DB::ISource::work() @ 0x000000001228fcc3 in /usr/bin/clickhouse 4. DB::ExecutionThreadContext::executeTask() @ 0x00000000122a78ba in /usr/bin/clickhouse 5. DB::PipelineExecutor::executeStepImpl(unsigned long, std::atomic<bool>*) @ 0x000000001229e5d0 in /usr/bin/clickhouse 6. DB::PipelineExecutor::execute(unsigned long, bool) @ 0x000000001229d860 in /usr/bin/clickhouse 7. void std::__function::__policy_invoker<void ()>::__call_impl<std::__function::__default_alloc_func<ThreadFromGlobalPoolImpl<true>::ThreadFromGlobalPoolImpl<DB::PullingAsyncPipelineExecutor::pull(DB::Chunk&, unsigned long)::$_0>(DB::PullingAsyncPipelineExecutor::pull(DB::Chunk&, unsigned long)::$_0&&)::'lambda'(), void ()>>(std::__function::__policy_storage const*) @ 0x00000000122ab1cf in /usr/bin/clickhouse 8. void* std::__thread_proxy[abi:v15000]<std::tuple<std::unique_ptr<std::__thread_struct, std::default_delete<std::__thread_struct>>, void ThreadPoolImpl<std::thread>::scheduleImpl<void>(std::function<void ()>, Priority, std::optional<unsigned long>, bool)::'lambda0'()>>(void*) @ 0x000000000c5e45d3 in /usr/bin/clickhouse 9. ? @ 0x00007429a8071609 in ? 10. ? @ 0x00007429a7f96133 in ?",
                    type: 'Error',
                    mechanism: {
                        type: 'onerror',
                        handled: false,
                        synthetic: true,
                    },
                    stacktrace: {
                        type: 'resolved',
                        frames: [
                            {
                                column: 0,
                                source: 'https://app.posthog.com/home',
                                resolved_name: '?',
                                in_app: true,
                                line: 0,
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
        $exception_list: [
            {
                value: 'ResizeObserver loop limit exceeded',
                type: 'Error',
            },
        ],
        ...properties,
    }
}

export function StacktracelessSafariScriptError(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_list: [{ type: 'ScriptError', value: 'Script error.', mechanism: { synthetic: true } }],
            })}
            eventId="error"
        />
    )
}

export function StacktracelessImportModuleError(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_list: [
                    {
                        type: 'UnhandledRejection',
                        value: "Importing module '/static/chunk-PIJHGO7Q.js' is not found.",
                        mechanism: { handled: true },
                    },
                ],
            })}
            eventId="error"
        />
    )
}

export function AnonymousErrorWithStackTrace(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_list: [
                    {
                        type: 'Error',
                        value: 'wat123',
                        stacktrace: {
                            type: 'resolved',
                            frames: [
                                {
                                    source: '<anonymous>',
                                    resolved_name: '?',
                                    in_app: true,
                                    line: 1,
                                    column: 26,
                                },
                            ],
                        },
                    },
                ],
            })}
            eventId="error"
        />
    )
}

export function ChainedErrorStack(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_list: [
                    {
                        module: null,
                        type: 'ZeroDivisionError',
                        value: 'division by zero',
                        stacktrace: {
                            type: 'resolved',
                            frames: [
                                {
                                    source: '/posthog-python/example2.py',
                                    resolved_name: 'will_raise',
                                    line: 33,
                                    in_app: true,
                                },
                                {
                                    source: '/posthog-python/example2.py',
                                    resolved_name: 'more_obfuscation',
                                    line: 29,
                                },
                            ],
                        },
                    },
                    {
                        module: '__main__',
                        type: 'CustomException',
                        value: 'This is a custom exception',
                        stacktrace: {
                            type: 'resolved',
                            frames: [
                                {
                                    source: '/Users/neilkakkar/Project/posthog-python/example2.py',
                                    resolved_name: '<module>',
                                    line: 37,
                                    in_app: true,
                                },
                                {
                                    source: '/Users/neilkakkar/Project/posthog-python/example2.py',
                                    resolved_name: 'will_raise',
                                    line: 35,
                                    in_app: true,
                                },
                            ],
                        },
                    },
                ],
            })}
            eventId="error"
        />
    )
}

export function StackTraceWithLineContext(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_list: [
                    {
                        type: 'Error',
                        value: 'wat123',
                        stacktrace: {
                            type: 'resolved',
                            frames: [
                                {
                                    raw_id: 'rawId',
                                    source: '<anonymous>',
                                    resolved_name: '?',
                                    in_app: true,
                                    line: 1,
                                    column: 26,
                                    lang: 'javascript',
                                },
                            ],
                        },
                    },
                ],
            })}
            eventId="error"
        />
    )
}

export function WithCymbalErrors(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_list: [
                    {
                        type: 'Error',
                        value: 'wat123',
                    },
                ],
                $cymbal_errors: ['This is an ingestion error', 'This is a second one'],
            })}
            eventId="error"
        />
    )
}

export function SentryStackTrace(): JSX.Element {
    return <ErrorDisplay eventProperties={errorProperties({ $exception_list: [] })} eventId="error" />
}

export function LegacyEventProperties(): JSX.Element {
    return (
        <ErrorDisplay
            eventProperties={errorProperties({
                $exception_message: 'ResizeObserver loop limit exceeded',
                $exception_type: 'Error',
                $exception_personURL: 'https://app.posthog.com/person/the-person-id',
                $exception_synthetic: true,
            })}
            eventId="error"
        />
    )
}
