import { IconFlag } from '@posthog/icons'
import { TitledSnack } from 'lib/components/TitledSnack'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import posthog from 'posthog-js'

import { EventType } from '~/types'

interface StackFrame {
    filename: string
    lineno: number
    colno: number
    function: string
    context_line?: string
}

interface ExceptionTrace {
    stacktrace: {
        frames: StackFrame[]
    }
    module: string
    type: string
    value: string
}

function parseToFrames(rawTrace: string): StackFrame[] {
    return JSON.parse(rawTrace)
}

function StackTrace({ rawTrace }: { rawTrace: string }): JSX.Element | null {
    try {
        const frames = parseToFrames(rawTrace)
        return (
            <>
                {frames.length ? (
                    frames.map((frame, index) => {
                        const { filename, lineno, colno, function: functionName, context_line } = frame

                        return (
                            <TitledSnack
                                key={index}
                                title={functionName}
                                value={
                                    <>
                                        {filename}:{lineno}:{colno}
                                        {context_line ? `:${context_line}` : ''}
                                    </>
                                }
                            />
                        )
                    })
                ) : (
                    <LemonTag>Empty stack trace</LemonTag>
                )}
            </>
        )
    } catch (e: any) {
        //very meta
        posthog.capture('Cannot parse stack trace in Exception event', { tag: 'error-display-stack-trace', e })
        return <LemonTag type="caution">Error parsing stack trace</LemonTag>
    }
}

function ChainedStackTraces({ exceptionList }: { exceptionList: ExceptionTrace[] }): JSX.Element {
    return (
        <>
            <LemonDivider dashed={true} />
            <h2 className="mb-0">Stack Trace</h2>
            {exceptionList.map(({ stacktrace, value }, index) => {
                return (
                    <div key={index} className="flex flex-col gap-1 mt-6">
                        <h3 className="mb-0">{value}</h3>
                        <StackTrace rawTrace={JSON.stringify(stacktrace.frames)} />
                    </div>
                )
            })}
        </>
    )
}

function ActiveFlags({ flags }: { flags: string[] }): JSX.Element {
    return (
        <>
            {flags && flags.length ? (
                <div className="flex flex-row gap-2 flex-wrap">
                    {flags.map((flag, index) => {
                        return (
                            <div key={index} className="border rounded px-1.5 py-1 bg-primary-alt-highlight text-muted">
                                <IconFlag className="pr-1" />

                                {flag}
                            </div>
                        )
                    })}
                </div>
            ) : (
                <div>No active feature flags</div>
            )}
        </>
    )
}

export function getExceptionPropertiesFrom(eventProperties: Record<string, any>): Record<string, any> {
    const {
        $exception_type,
        $exception_message,
        $exception_synthetic,
        $lib,
        $lib_version,
        $browser,
        $browser_version,
        $os,
        $os_version,
        $active_feature_flags,
        $sentry_url,
        $sentry_exception,
        $level,
    } = eventProperties

    let $exception_stack_trace_raw = eventProperties.$exception_stack_trace_raw
    let $exception_list = eventProperties.$exception_list
    // exception autocapture sets $exception_stack_trace_raw as a string
    // if it isn't present then this is probably a sentry exception.
    // try and grab the frames from that
    if (!$exception_stack_trace_raw?.length && $sentry_exception) {
        if (Array.isArray($sentry_exception.values)) {
            const firstException = $sentry_exception.values[0]
            if (firstException.stacktrace) {
                $exception_stack_trace_raw = JSON.stringify(firstException.stacktrace.frames)
            }
        }
    }
    // exception autocapture sets $exception_list for chained exceptions.
    // If it's not present, get this list from the sentry_exception
    if (!$exception_list && $sentry_exception) {
        if (Array.isArray($sentry_exception.values)) {
            $exception_list = $sentry_exception.values
        }
    }

    return {
        $exception_type,
        $exception_message,
        $exception_synthetic,
        $lib,
        $lib_version,
        $browser,
        $browser_version,
        $os,
        $os_version,
        $active_feature_flags,
        $sentry_url,
        $exception_stack_trace_raw,
        $exception_list,
        $level,
    }
}

export function ErrorDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const {
        $exception_type,
        $exception_message,
        $exception_synthetic,
        $lib,
        $lib_version,
        $browser,
        $browser_version,
        $os,
        $os_version,
        $active_feature_flags,
        $sentry_url,
        $exception_stack_trace_raw,
        $exception_list,
        $level,
    } = getExceptionPropertiesFrom(eventProperties)

    return (
        <div className="flex flex-col space-y-2 pr-4 pb-2">
            <h1 className="mb-0">{$exception_message}</h1>
            <div className="flex flex-row gap-2 flex-wrap">
                <LemonTag type="danger">{$exception_type || $level}</LemonTag>
                <TitledSnack
                    type="success"
                    title="captured by"
                    value={
                        <>
                            {$sentry_url ? (
                                <Link
                                    className="text-3000 hover:underline decoration-primary-alt cursor-pointer"
                                    to={$sentry_url}
                                    target="_blank"
                                >
                                    Sentry
                                </Link>
                            ) : (
                                <>PostHog</>
                            )}
                        </>
                    }
                />
                <TitledSnack title="synthetic" value={$exception_synthetic ? 'true' : 'false'} />
                <TitledSnack title="library" value={`${$lib} ${$lib_version}`} />
                <TitledSnack title="browser" value={$browser ? `${$browser} ${$browser_version}` : 'unknown'} />
                <TitledSnack title="os" value={$os ? `${$os} ${$os_version}` : 'unknown'} />
            </div>
            {$exception_list?.length ? (
                <ChainedStackTraces exceptionList={$exception_list} />
            ) : $exception_stack_trace_raw?.length ? (
                <>
                    <LemonDivider dashed={true} />
                    <div className="flex flex-col gap-1 mt-6">
                        <h2 className="mb-0">Stack Trace</h2>
                        <StackTrace rawTrace={$exception_stack_trace_raw} />
                    </div>
                </>
            ) : null}
            <LemonDivider dashed={true} />
            <div className="flex flex-col gap-1 mt-6">
                <h2 className="mb-0">Active Feature Flags</h2>
                <ActiveFlags flags={$active_feature_flags} />
            </div>
        </div>
    )
}
