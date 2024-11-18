import './ErrorDisplay.scss'

import { IconFlag } from '@posthog/icons'
import { LemonCollapse } from '@posthog/lemon-ui'
import { TitledSnack } from 'lib/components/TitledSnack'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { useState } from 'react'

import { EventType } from '~/types'

import { StackFrame } from './stackFrameLogic'

interface RawStackTrace {
    type: 'raw'
    frames: StackFrame[]
}
interface ResolvedStackTrace {
    type: 'resolved'
    frames: StackFrame[]
}

interface Exception {
    stacktrace: ResolvedStackTrace | RawStackTrace
    module: string
    type: string
    value: string
}

function StackTrace({ frames, showAllFrames }: { frames: StackFrame[]; showAllFrames: boolean }): JSX.Element | null {
    const displayFrames = showAllFrames ? frames : frames.filter((f) => f.in_app)

    const panels = displayFrames.map(({ filename, lineno, colno, function: functionName }, index) => {
        return {
            key: index,
            header: (
                <div className="flex flex-wrap space-x-0.5">
                    <span>{filename}</span>
                    {functionName ? (
                        <div className="flex space-x-0.5">
                            <span className="text-muted">in</span>
                            <span>{functionName}</span>
                        </div>
                    ) : null}
                    {lineno && colno ? (
                        <div className="flex space-x-0.5">
                            <span className="text-muted">at line</span>
                            <span>
                                {lineno}:{colno}
                            </span>
                        </div>
                    ) : null}
                </div>
            ),
            content: null,
        }
    })

    return <LemonCollapse defaultActiveKeys={[]} multiple panels={panels} size="xsmall" />
}

function ChainedStackTraces({ exceptionList }: { exceptionList: Exception[] }): JSX.Element {
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
                    <div key={index} className="ErrorDisplay__stacktrace flex flex-col gap-1 mt-6">
                        <h3 className="mb-0">{value}</h3>
                        <StackTrace frames={frames || []} showAllFrames={showAllFrames} />
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
