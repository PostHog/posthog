import './StackTraces.scss'

import { LemonCollapse, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { useEffect, useMemo } from 'react'
import { match, P } from 'ts-pattern'

import { CodeLine, getLanguage, Language } from '../CodeSnippet/CodeSnippet'
import { FingerprintRecordPartDisplay } from './FingerprintRecordPartDisplay'
import { FingerprintRecordPart, stackFrameLogic } from './stackFrameLogic'
import {
    ErrorTrackingException,
    ErrorTrackingStackFrame,
    ErrorTrackingStackFrameContext,
    ErrorTrackingStackFrameContextLine,
} from './types'

export type ExceptionHeaderProps = {
    id?: string
    type: string
    value: string
    part?: FingerprintRecordPart
}

function ExceptionHeader({ type, value, part }: ExceptionHeaderProps): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5 mb-2">
            <h3 className="StackTrace__type mb-0" title={type}>
                {type}
                {part && <FingerprintRecordPartDisplay className="ml-1" part={part} />}
            </h3>
            <div className="StackTrace__value line-clamp-2 text-secondary italic text-xs" title={value}>
                {value}
            </div>
        </div>
    )
}

export function ChainedStackTraces({
    exceptionList,
    showAllFrames,
    renderExceptionHeader,
    embedded = false,
    fingerprintRecords = [],
}: {
    renderExceptionHeader?: (props: ExceptionHeaderProps) => React.ReactNode
    exceptionList: ErrorTrackingException[]
    fingerprintRecords?: FingerprintRecordPart[]
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
        <div className="flex flex-col gap-y-2">
            {exceptionList.map(({ stacktrace, value, type, id }, index) => {
                if (stacktrace && stacktrace.type === 'resolved') {
                    const { frames } = stacktrace
                    const hasOnlyNonInAppFrames = frames?.every((frame) => !frame.in_app)
                    const part = fingerprintRecords.find((record) => record.type == 'exception' && record.id === id)
                    const traceHeaderProps = { id, type, value, part }
                    return (
                        <div
                            key={id ?? index}
                            className={clsx('StackTrace flex flex-col', embedded && 'StackTrace--embedded')}
                        >
                            {match(renderExceptionHeader)
                                .with(P.nullish, () => <ExceptionHeader {...traceHeaderProps} />)
                                .with(P.any, () => renderExceptionHeader!(traceHeaderProps))
                                .exhaustive()}
                            {match([showAllFrames, hasOnlyNonInAppFrames])
                                .with([false, true], () => null)
                                .otherwise(() => (
                                    <Trace
                                        frames={frames || []}
                                        showAllFrames={showAllFrames}
                                        embedded={embedded}
                                        fingerprintRecords={fingerprintRecords}
                                    />
                                ))}
                        </div>
                    )
                }
            })}
        </div>
    )
}

function Trace({
    frames,
    fingerprintRecords,
    showAllFrames,
    embedded,
}: {
    frames: ErrorTrackingStackFrame[]
    fingerprintRecords: FingerprintRecordPart[]
    showAllFrames: boolean
    embedded: boolean
}): JSX.Element | null {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const checkers = useFingerprintRecords(fingerprintRecords)
    const displayFrames = showAllFrames ? frames : frames.filter((f) => f.in_app)

    const panels = displayFrames.map(
        ({ raw_id, source, line, column, resolved_name, lang, resolved, resolve_failure, in_app }) => {
            const record = stackFrameRecords[raw_id]
            const part = checkers.getFramePart(raw_id)
            // const isUsedInFingerprint = checkers.includesFrame(raw_id)
            // const isHighlighted = checkers.isFrameHighlighted(raw_id)

            return {
                key: raw_id,
                header: (
                    <div className="flex flex-1 justify-between items-center">
                        <div className="flex flex-wrap gap-x-1">
                            <span>{source}</span>
                            {resolved_name ? (
                                <div className="flex gap-x-1">
                                    <span className="text-secondary">in</span>
                                    <span>{resolved_name}</span>
                                </div>
                            ) : null}
                            {line ? (
                                <div className="flex gap-x-1">
                                    <span className="text-secondary">@</span>
                                    <span>
                                        {line}
                                        {column && `:${column}`}
                                    </span>
                                </div>
                            ) : null}
                        </div>
                        <div className="flex gap-x-1 items-center">
                            {part && <FingerprintRecordPartDisplay part={part} />}
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
                        <div
                            onClick={(e) => {
                                e.stopPropagation()
                                e.preventDefault()
                            }}
                        >
                            <FrameContext context={record.context} language={getLanguage(lang)} />
                        </div>
                    ) : null,
                className: 'p-0',
            }
        }
    )

    return <LemonCollapse embedded={embedded} multiple panels={panels} size="xsmall" />
}

export type FingerprintCheckers = {
    getExceptionPart(excId: string): FingerprintRecordPart | undefined
    getFramePart(frameId: string): FingerprintRecordPart | undefined
}

function useFingerprintRecords(fingerprintRecords: FingerprintRecordPart[]): FingerprintCheckers {
    return useMemo(() => {
        return {
            getExceptionPart(excId: string) {
                return fingerprintRecords.find((record) => record.type === 'exception' && record.id === excId)
            },
            getFramePart(frameId: string) {
                return fingerprintRecords.find((record) => record.type === 'frame' && record.raw_id === frameId)
            },
        }
    }, [fingerprintRecords])
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
        <div className={highlight ? 'bg-fill-error-highlight' : 'bg-surface-primary'}>
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
