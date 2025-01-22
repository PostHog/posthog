import './StackTraces.scss'

import { LemonCollapse, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { useEffect } from 'react'

import { CodeLine, getLanguage, Language } from '../CodeSnippet/CodeSnippet'
import { stackFrameLogic } from './stackFrameLogic'
import {
    ErrorTrackingException,
    ErrorTrackingStackFrame,
    ErrorTrackingStackFrameContext,
    ErrorTrackingStackFrameContextLine,
} from './types'

export function ChainedStackTraces({
    exceptionList,
    showAllFrames,
    embedded = false,
}: {
    exceptionList: ErrorTrackingException[]
    showAllFrames: boolean
    embedded?: boolean
}): JSX.Element {
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
            {exceptionList.map(({ stacktrace, value, type }, index) => {
                if (stacktrace && stacktrace.type === 'resolved') {
                    const { frames } = stacktrace
                    if (!showAllFrames && !frames?.some((frame) => frame.in_app)) {
                        // if we're not showing all frames and there are no in_app frames, skip this exception
                        return null
                    }

                    return (
                        <div
                            key={index}
                            className={clsx('StackTrace flex flex-col space-y-2', embedded && 'StackTrace--embedded')}
                        >
                            <div className="space-y-0.5">
                                <h3 className="StackTrace__type mb-0">{type}</h3>
                                <div className="StackTrace__value line-clamp-2 text-muted italic text-xs">{value}</div>
                            </div>
                            <Trace frames={frames || []} showAllFrames={showAllFrames} embedded={embedded} />
                        </div>
                    )
                }
            })}
        </>
    )
}

function Trace({
    frames,
    showAllFrames,
    embedded,
}: {
    frames: ErrorTrackingStackFrame[]
    showAllFrames: boolean
    embedded: boolean
}): JSX.Element | null {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const displayFrames = showAllFrames ? frames : frames.filter((f) => f.in_app)

    const panels = displayFrames.map(
        ({ raw_id, source, line, column, resolved_name, lang, resolved, resolve_failure, in_app }, index) => {
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
                        <div className="space-x-1">
                            {in_app && <LemonTag>In App</LemonTag>}
                            {!resolved && (
                                <Tooltip title={resolve_failure}>
                                    <LemonTag>Unresolved</LemonTag>
                                </Tooltip>
                            )}
                        </div>
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

    return <LemonCollapse embedded={embedded} multiple panels={panels} size="xsmall" />
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
        <div className={highlight ? 'bg-accent-3000' : 'bg-bg-light'}>
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
