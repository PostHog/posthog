import { IconFlag } from '@posthog/icons'
import { TitledSnack } from 'lib/components/TitledSnack'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import posthog from 'posthog-js'
import { useState } from 'react'

import { EventType } from '~/types'

interface StackFrame {
    filename: string
    lineno: number
    colno: number
    function: string
    context_line?: string
    in_app?: boolean
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

function StackTrace({ rawTrace, showAllFrames }: { rawTrace: string; showAllFrames: boolean }): JSX.Element | null {
    try {
        const frames = parseToFrames(rawTrace)
        return (
            <>
                {frames.length ? (
                    frames.map((frame, index) => {
                        const { filename, lineno, colno, function: functionName, context_line, in_app } = frame

                        return showAllFrames || in_app ? (
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
                        ) : null
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
    const [showAllFrames, setShowAllFrames] = useState(false)

    return (
        <>
            <LemonDivider dashed={true} />
            <div className="flex gap-1 mt-6 justify-between items-center">
                <h2 className="mb-0">Stack Trace</h2>
                <LemonSwitch
                    checked={showAllFrames}
                    label="Show entire stack trace"
                    onChange={() => {
                        setShowAllFrames(!showAllFrames)
                    }}
                />
            </div>
            {exceptionList.map(({ stacktrace, value }, index) => {
                const { frames } = stacktrace || {}
                if (!showAllFrames && !frames?.some((frame) => frame.in_app)) {
                    // if we're not showing all frames and there are no in_app frames, skip this exception
                    return null
                }

                return (
                    <div key={index} className="flex flex-col gap-1 mt-6">
                        <h3 className="mb-0">{value}</h3>
                        <StackTrace rawTrace={JSON.stringify(frames || [])} showAllFrames={showAllFrames} />
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

    let $exception_type = eventProperties.$exception_type
    let $exception_message = eventProperties.$exception_message
    let $exception_synthetic = eventProperties.$exception_synthetic
    let $exception_list = eventProperties.$exception_list

    // exception autocapture sets $exception_list for all exceptions.
    // If it's not present, then this is probably a sentry exception. Get this list from the sentry_exception
    if (!$exception_list?.length && $sentry_exception) {
        if (Array.isArray($sentry_exception.values)) {
            $exception_list = $sentry_exception.values
        }
    }

    if (!$exception_type) {
        $exception_type = $exception_list?.[0]?.type
    }
    if (!$exception_message) {
        $exception_message = $exception_list?.[0]?.value
    }
    if ($exception_synthetic == undefined) {
        $exception_synthetic = $exception_list?.[0]?.mechanism?.synthetic
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
            {$exception_list?.length ? <ChainedStackTraces exceptionList={$exception_list} /> : null}
            <LemonDivider dashed={true} />
            <div className="flex flex-col gap-1 mt-6">
                <h2 className="mb-0">Active Feature Flags</h2>
                <ActiveFlags flags={$active_feature_flags} />
            </div>
        </div>
    )
}
