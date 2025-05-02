import './StackTraces.scss'

import { IconBox } from '@posthog/icons'
import { LemonCollapse, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { MouseEvent, useEffect, useMemo } from 'react'
import { cancelEvent } from 'scenes/error-tracking/utils'
import { match, P } from 'ts-pattern'

import { CodeLine, getLanguage, Language } from '../CodeSnippet/CodeSnippet'
import { CopyToClipboardInline } from '../CopyToClipboard'
import { FingerprintRecordPartDisplay } from './FingerprintRecordPartDisplay'
import { FingerprintRecordPart, stackFrameLogic } from './stackFrameLogic'
import {
    ErrorTrackingException,
    ErrorTrackingStackFrame,
    ErrorTrackingStackFrameContext,
    ErrorTrackingStackFrameContextLine,
} from './types'
import { stacktraceHasInAppFrames } from './utils'

export type ExceptionHeaderProps = {
    id?: string
    type?: string
    value?: string
    loading: boolean
    part?: FingerprintRecordPart
}

function ExceptionHeader({ type, value, part }: ExceptionHeaderProps): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5 mb-2">
            <h3 className="StackTrace__type mb-0 flex items-center" title={type}>
                {type}
                {part && <FingerprintRecordPartDisplay className="ml-1" part={part} />}
            </h3>
            <div className="StackTrace__value line-clamp-2 text-secondary italic text-xs" title={value}>
                {value}
            </div>
        </div>
    )
}

type FrameContextClickHandler = (ctx: ErrorTrackingStackFrameContext, e: MouseEvent) => void

export function ChainedStackTraces({
    exceptionList,
    showAllFrames,
    renderExceptionHeader,
    onFrameContextClick,
    embedded = false,
    fingerprintRecords = [],
}: {
    renderExceptionHeader?: (props: ExceptionHeaderProps) => React.ReactNode
    exceptionList: ErrorTrackingException[]
    fingerprintRecords?: FingerprintRecordPart[]
    showAllFrames: boolean
    embedded?: boolean
    onFrameContextClick?: FrameContextClickHandler
}): JSX.Element {
    const { loadFromRawIds } = useActions(stackFrameLogic)
    const getters = useFingerprintGetters(fingerprintRecords)

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
                const displayTrace = shouldDisplayTrace(stacktrace, showAllFrames)
                const part = getters.getExceptionPart(id)
                const traceHeaderProps = { id, type, value, part, loading: false }
                return (
                    <div
                        key={id ?? index}
                        className={clsx('StackTrace flex flex-col', embedded && 'StackTrace--embedded')}
                    >
                        {match(renderExceptionHeader)
                            .with(P.nullish, () => <ExceptionHeader {...traceHeaderProps} />)
                            .with(P.any, () => renderExceptionHeader!(traceHeaderProps))
                            .exhaustive()}
                        {displayTrace && (
                            <Trace
                                frames={stacktrace?.frames || []}
                                showAllFrames={showAllFrames}
                                embedded={embedded}
                                getters={getters}
                                onFrameContextClick={onFrameContextClick}
                            />
                        )}
                    </div>
                )
            })}
        </div>
    )
}

function shouldDisplayTrace(stacktrace: ErrorTrackingException['stacktrace'], showAllFrames: boolean): boolean {
    if (!stacktrace) {
        return false
    }
    if (stacktrace.type != 'resolved') {
        return false
    }
    if (showAllFrames) {
        return true
    }
    const hasInAppFrames = stacktraceHasInAppFrames(stacktrace)
    return hasInAppFrames
}

function Trace({
    frames,
    showAllFrames,
    embedded,
    getters,
    onFrameContextClick,
}: {
    frames: ErrorTrackingStackFrame[]
    showAllFrames: boolean
    embedded: boolean
    getters?: FingerprintGetters
    onFrameContextClick?: FrameContextClickHandler
}): JSX.Element | null {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const displayFrames = showAllFrames ? frames : frames.filter((f) => f.in_app)

    const panels = displayFrames.map((frame: ErrorTrackingStackFrame, idx) => {
        const { raw_id, lang } = frame
        const record = stackFrameRecords[raw_id]
        return {
            key: idx,
            header: <FrameHeaderDisplay frame={frame} getters={getters} />,
            content:
                record && record.context ? (
                    <div onClick={(e) => onFrameContextClick?.(record.context!, e)}>
                        <FrameContext context={record.context} language={getLanguage(lang)} />
                    </div>
                ) : null,
            className: 'p-0',
        }
    })

    return <LemonCollapse embedded={embedded} multiple panels={panels} size="xsmall" />
}

export function FrameHeaderDisplay({
    frame,
    getters,
}: {
    frame: ErrorTrackingStackFrame
    getters?: FingerprintGetters
}): JSX.Element {
    const { raw_id, source, line, column, resolved_name, resolved, resolve_failure, in_app } = frame
    const part = getters?.getFramePart(raw_id)
    return (
        <div className="flex flex-1 justify-between items-center h-full">
            <div className="flex flex-wrap gap-x-1">
                {resolved_name ? (
                    <div className="flex">
                        <span>{resolved_name}</span>
                    </div>
                ) : null}
                <div className="flex font-light text-xs">
                    <span>{source}</span>
                    {line ? (
                        <>
                            <span className="text-secondary">@</span>
                            <span>
                                {line}
                                {column && `:${column}`}
                            </span>
                        </>
                    ) : null}
                </div>
            </div>
            <div className="flex gap-x-1 items-center justify-end">
                {resolved && source && (
                    <span onClick={cancelEvent} className="text-secondary">
                        <CopyToClipboardInline
                            tooltipMessage="Copy file name"
                            iconSize="xsmall"
                            explicitValue={source}
                        />
                    </span>
                )}
                {part && <FingerprintRecordPartDisplay part={part} />}
                {!in_app && (
                    <Tooltip title="Vendor frame">
                        <IconBox className="mr-0.5 text-secondary" fontSize={15} />
                    </Tooltip>
                )}
                {!resolved && (
                    <Tooltip title={resolve_failure}>
                        <LemonTag>Unresolved</LemonTag>
                    </Tooltip>
                )}
            </div>
        </div>
    )
}

export type FingerprintGetters = {
    getExceptionPart(excId: string): FingerprintRecordPart | undefined
    getFramePart(frameId: string): FingerprintRecordPart | undefined
}

function useFingerprintGetters(fingerprintRecords: FingerprintRecordPart[]): FingerprintGetters {
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
