import './StackTraces.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { MouseEvent, useState } from 'react'
import { P, match } from 'ts-pattern'

import { IconBox } from '@posthog/icons'
import { LemonBanner, LemonCollapse, Link, Tooltip } from '@posthog/lemon-ui'
import { cancelEvent } from '@posthog/products-error-tracking/frontend/utils'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

import { CodeLine, Language, getLanguage } from '../CodeSnippet/CodeSnippet'
import { CopyToClipboardInline } from '../CopyToClipboard'
import { FingerprintRecordPartDisplay } from './FingerprintRecordPartDisplay'
import { GitProviderFileLink } from './GitProviderFileLink'
import { errorPropertiesLogic } from './errorPropertiesLogic'
import { framesCodeSourceLogic } from './framesCodeSourceLogic'
import { stackFrameLogic } from './stackFrameLogic'
import {
    ErrorTrackingException,
    ErrorTrackingStackFrame,
    ErrorTrackingStackFrameContext,
    ErrorTrackingStackFrameContextLine,
    FingerprintRecordPart,
} from './types'
import { formatResolvedName, formatType, stacktraceHasInAppFrames } from './utils'

export type ExceptionHeaderProps = {
    id?: string
    exception: ErrorTrackingException
    loading: boolean
    part?: FingerprintRecordPart
}

function ExceptionHeader({ exception, part }: ExceptionHeaderProps): JSX.Element {
    const type = formatType(exception)
    const value = exception.value

    return (
        <div className="flex flex-col gap-0.5 mb-2">
            <h3 className="StackTrace__type mb-0 flex items-center" title={type}>
                {type}
                {part && <FingerprintRecordPartDisplay className="ml-1" part={part} />}
            </h3>
            {value && (
                <div className="StackTrace__value line-clamp-2 text-secondary italic text-xs" title={value}>
                    {value}
                </div>
            )}
        </div>
    )
}

type FrameContextClickHandler = (ctx: ErrorTrackingStackFrameContext, e: MouseEvent) => void

export function ChainedStackTraces({
    showAllFrames,
    renderExceptionHeader,
    onFrameContextClick,
    onFirstFrameExpanded,
    embedded = false,
}: {
    renderExceptionHeader?: (props: ExceptionHeaderProps) => React.ReactNode
    fingerprintRecords?: FingerprintRecordPart[]
    showAllFrames: boolean
    embedded?: boolean
    onFrameContextClick?: FrameContextClickHandler
    onFirstFrameExpanded?: () => void
}): JSX.Element {
    const { exceptionList, exceptionAttributes, getExceptionFingerprint } = useValues(errorPropertiesLogic)
    const [hasCalledOnFirstExpanded, setHasCalledOnFirstExpanded] = useState<boolean>(false)

    const handleFrameExpanded = (): void => {
        if (onFirstFrameExpanded && !hasCalledOnFirstExpanded) {
            setHasCalledOnFirstExpanded(true)
            onFirstFrameExpanded()
        }
    }

    const isScriptError =
        exceptionAttributes &&
        exceptionAttributes.type === 'Error' &&
        exceptionAttributes.runtime === 'web' &&
        exceptionAttributes.value === 'Script error'

    return (
        <div className="flex flex-col gap-y-2">
            {exceptionList.map((exception, index) => {
                const { stacktrace, id } = exception
                const displayTrace = shouldDisplayTrace(stacktrace, showAllFrames)
                const part = getExceptionFingerprint(id)
                const traceHeaderProps = { id, exception, part, loading: false }

                return (
                    <div
                        key={id ?? index}
                        className={clsx('StackTrace flex flex-col', embedded && 'StackTrace--embedded')}
                    >
                        {match(renderExceptionHeader)
                            .with(P.nullish, () => <ExceptionHeader {...traceHeaderProps} />)
                            .with(P.any, () => renderExceptionHeader!(traceHeaderProps))
                            .exhaustive()}
                        {isScriptError && (
                            <LemonBanner type="warning">
                                This error occurs when JavaScript exceptions are thrown from a third-party script but
                                details are hidden due to cross-origin restrictions.{' '}
                                <Link
                                    to="https://posthog.com/docs/error-tracking/common-questions#what-is-a-script-error-with-no-stack-traces"
                                    target="_blank"
                                >
                                    Read our docs
                                </Link>{' '}
                                to learn how to get the full exception context.
                            </LemonBanner>
                        )}
                        {displayTrace && (
                            <Trace
                                frames={stacktrace?.frames || []}
                                showAllFrames={showAllFrames}
                                embedded={embedded}
                                onFrameContextClick={onFrameContextClick}
                                onFrameExpanded={handleFrameExpanded}
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
    onFrameContextClick,
    onFrameExpanded,
}: {
    frames: ErrorTrackingStackFrame[]
    showAllFrames: boolean
    embedded: boolean
    onFrameExpanded: () => void
    onFrameContextClick?: FrameContextClickHandler
}): JSX.Element | null {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const displayFrames = showAllFrames ? frames : frames.filter((f) => f.in_app)

    const panels = displayFrames.map((frame: ErrorTrackingStackFrame, idx) => {
        const { raw_id, lang } = frame
        const record = stackFrameRecords[raw_id]
        return {
            key: idx,
            header: <FrameHeaderDisplay frame={frame} />,
            content:
                record && record.context ? (
                    <div onClick={(e) => onFrameContextClick?.(record.context!, e)}>
                        <FrameContext context={record.context} language={getLanguage(lang)} />
                    </div>
                ) : null,
            className: 'p-0',
        }
    })

    return <LemonCollapse embedded={embedded} multiple panels={panels} size="xsmall" onChange={onFrameExpanded} />
}

export function FrameHeaderDisplay({ frame }: { frame: ErrorTrackingStackFrame }): JSX.Element {
    const { raw_id, source, line, column, resolved, resolve_failure, in_app } = frame
    const { getFrameFingerprint } = useValues(errorPropertiesLogic)
    const { getSourceDataForFrame } = useValues(framesCodeSourceLogic)

    const part = getFrameFingerprint(raw_id)
    const resolvedName = formatResolvedName(frame)
    const sourceData = getSourceDataForFrame(raw_id)

    return (
        <div className="flex flex-1 justify-between items-center h-full">
            <div className="flex flex-wrap gap-x-1">
                {resolvedName ? (
                    <div className="flex">
                        <span>{resolvedName}</span>
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
                {in_app && sourceData?.url && <GitProviderFileLink sourceData={sourceData} />}
                {resolved && source && (
                    <span onClick={cancelEvent} className="text-secondary">
                        <CopyToClipboardInline
                            tooltipMessage="Copy file name"
                            iconSize="xsmall"
                            explicitValue={source}
                            iconMargin={false}
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
