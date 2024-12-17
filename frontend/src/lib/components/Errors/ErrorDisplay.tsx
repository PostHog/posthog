import './ErrorDisplay.scss'

import { LemonBanner, LemonCollapse, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TitledSnack } from 'lib/components/TitledSnack'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { useEffect, useState } from 'react'

import { EventType } from '~/types'

import { CodeLine, getLanguage, Language } from '../CodeSnippet/CodeSnippet'
import { stackFrameLogic } from './stackFrameLogic'
import {
    ErrorTrackingException,
    ErrorTrackingStackFrame,
    ErrorTrackingStackFrameContext,
    ErrorTrackingStackFrameContextLine,
} from './types'

function StackTrace({
    frames,
    showAllFrames,
}: {
    frames: ErrorTrackingStackFrame[]
    showAllFrames: boolean
}): JSX.Element | null {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const displayFrames = showAllFrames ? frames : frames.filter((f) => f.in_app)

    const panels = displayFrames.map(
        ({ raw_id, source, line, column, resolved_name, lang, resolved, resolve_failure }, index) => {
            const record = stackFrameRecords[raw_id]
            return {
                key: index,
                header: (
                    <div className="flex flex-1 justify-between items-center">
                        <div className="flex flex-wrap space-x-0.5">
                            <span>{source}</span>
                            {resolved_name ? (
                                <div className="flex space-x-0.5">
                                    <span className="text-muted">in</span>
                                    <span>{resolved_name}</span>
                                </div>
                            ) : null}
                            {line ? (
                                <div className="flex space-x-0.5">
                                    <span className="text-muted">@</span>
                                    <span>
                                        {line}
                                        {column && `:${column}`}
                                    </span>
                                </div>
                            ) : null}
                        </div>
                        {!resolved && (
                            <div className="flex items-center space-x-1">
                                <Tooltip title={resolve_failure}>
                                    <LemonTag>Unresolved</LemonTag>
                                </Tooltip>
                            </div>
                        )}
                    </div>
                ),
                content:
                    record && record.context ? (
                        <FrameContext context={record.context} language={getLanguage(lang)} />
                    ) : null,
                className: 'p-0',
            }
        }
    )

    return <LemonCollapse multiple panels={panels} size="xsmall" />
}

function FrameContext({
    context,
    language,
}: {
    context: ErrorTrackingStackFrameContext
    language: Language
}): JSX.Element {
    const { before, line, after } = context
    return (
        <>
            <FrameContextLine lines={before} language={language} />
            <FrameContextLine lines={[line]} language={language} highlight />
            <FrameContextLine lines={after} language={language} />
        </>
    )
}

function FrameContextLine({
    lines,
    language,
    highlight,
}: {
    lines: ErrorTrackingStackFrameContextLine[]
    language: Language
    highlight?: boolean
}): JSX.Element {
    return (
        <div className={highlight ? 'bg-[var(background-secondary)]' : 'bg-[var(--background-primary)]'}>
            {lines
                .sort((l) => l.number)
                .map(({ number, line }) => (
                    <div key={number} className="flex">
                        <div className="w-12 text-center">{number}</div>
                        <CodeLine text={line} wrapLines={true} language={language} />
                    </div>
                ))}
        </div>
    )
}
function ChainedStackTraces({ exceptionList }: { exceptionList: ErrorTrackingException[] }): JSX.Element {
    const hasAnyInApp = exceptionList.some(({ stacktrace }) => stacktrace?.frames?.some(({ in_app }) => in_app))
    const [showAllFrames, setShowAllFrames] = useState(!hasAnyInApp)
    const { loadFromRawIds } = useActions(stackFrameLogic)

    useEffect(() => {
        const frames: ErrorTrackingStackFrame[] = exceptionList.flatMap((e) => {
            const trace = e.stacktrace
            if (trace?.type === 'resolved') {
                return trace.frames
            }
            return []
        })
        loadFromRawIds(frames.map(({ raw_id }) => raw_id))
    }, [exceptionList, loadFromRawIds])

    return (
        <>
            <div className="flex gap-1 mt-6 justify-between items-center">
                <h3 className="mb-0">Stack Trace</h3>
                {hasAnyInApp ? (
                    <LemonSwitch
                        checked={showAllFrames}
                        label="Show entire stack trace"
                        onChange={() => {
                            setShowAllFrames(!showAllFrames)
                        }}
                    />
                ) : null}
            </div>
            {exceptionList.map(({ stacktrace, value }, index) => {
                if (stacktrace && stacktrace.type === 'resolved') {
                    const { frames } = stacktrace
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
                }
            })}
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
        $sentry_url,
        $exception_list,
        $level,
    } = getExceptionPropertiesFrom(eventProperties)

    const exceptionList: ErrorTrackingException[] | undefined = $exception_list
    const exceptionWithStack = exceptionList?.length && exceptionList.some((e) => !!e.stacktrace)
    const ingestionErrors: string[] | undefined = eventProperties['$cymbal_errors']

    return (
        <div className="flex flex-col space-y-2 pr-4 pb-2">
            <h1 className="mb-0">{$exception_message}</h1>
            <div className="flex flex-row gap-2 flex-wrap">
                <LemonTag type="danger">{$exception_type || $level}</LemonTag>
                <TitledSnack
                    type="success"
                    title="captured by"
                    value={
                        $sentry_url ? (
                            <Link
                                className="text-3000 hover:underline decoration-primary-alt cursor-pointer"
                                to={$sentry_url}
                                target="_blank"
                            >
                                Sentry
                            </Link>
                        ) : (
                            'PostHog'
                        )
                    }
                />
                <TitledSnack title="synthetic" value={$exception_synthetic ? 'true' : 'false'} />
                <TitledSnack title="library" value={`${$lib} ${$lib_version}`} />
                <TitledSnack title="browser" value={$browser ? `${$browser} ${$browser_version}` : 'unknown'} />
                <TitledSnack title="os" value={$os ? `${$os} ${$os_version}` : 'unknown'} />
            </div>

            {ingestionErrors || exceptionWithStack ? <LemonDivider dashed={true} /> : null}
            {ingestionErrors && (
                <>
                    <LemonBanner type="error">
                        <ul>
                            {ingestionErrors.map((e, i) => (
                                <li key={i}>{e}</li>
                            ))}
                        </ul>
                    </LemonBanner>
                </>
            )}
            {exceptionWithStack ? <ChainedStackTraces exceptionList={$exception_list} /> : null}
        </div>
    )
}
