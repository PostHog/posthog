import './CollapsibleFrameHeader.scss'

import { useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, useEffect, useRef } from 'react'
import { P, match } from 'ts-pattern'

import { IconBox, IconEllipsis, IconSpinner, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { cn } from 'lib/utils/css-classes'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { FingerprintRecordPartDisplay } from '../FingerprintRecordPartDisplay'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { formatFunctionName, getInstructionAddress } from '../utils'
import { FrameDropDownMenu } from './FrameDropDownMenu'

const UNKNOWN_FRAME_LABEL = 'Unknown frame'
const SYMBOL_SETS_DOC_LINK = 'https://posthog.com/docs/error-tracking/upload-source-maps'

export function CollapsibleFrameHeader({
    frame,
    record,
    recordLoading,
}: {
    frame: ErrorTrackingStackFrame
    record?: ErrorTrackingStackFrameRecord
    recordLoading: boolean
    expanded: boolean
}): JSX.Element {
    const { raw_id, source, line, column, resolved, resolve_failure, in_app, lang } = frame
    const { getFrameFingerprint } = useValues(errorPropertiesLogic)

    const part = getFrameFingerprint(raw_id)
    const functionName = formatFunctionName(frame)
    const hasRecordContext = !!record && !!record.context
    const sourceRef = useRef<HTMLSpanElement>(null)
    const functionRef = useRef<HTMLSpanElement>(null)
    const sourceLine = formatSourceLine(source, line, column)
    const instructionAddress = getInstructionAddress(frame)
    const isUnsymbolicated = !functionName && !sourceLine
    const sourceContent = sourceLine ?? instructionAddress ?? (functionName ? undefined : UNKNOWN_FRAME_LABEL)

    useEffect(() => {
        // If sourceRef is scrollable scroll to the end and add scrollable attribute
        if (sourceRef.current && sourceRef.current.scrollWidth > sourceRef.current.clientWidth) {
            let delta = sourceRef.current.scrollWidth - sourceRef.current.clientWidth
            sourceRef.current.scrollBy({ left: delta + 10 })
            sourceRef.current.setAttribute('scrollable', 'true')
        }
    }, [sourceRef, sourceContent])

    useEffect(() => {
        const el = functionRef.current
        // If functionRef is scrollable scroll to the end and add scrollable attribute
        if (el && el.scrollWidth > el.clientWidth) {
            let delta = el.scrollWidth - el.clientWidth
            el.scrollBy({ left: delta + 10 })
            el.setAttribute('scrollable', 'true')
        }
    }, [functionRef, sourceContent])

    return (
        <div className={cn('flex h-7 w-full bg-surface-popover')}>
            <Collapsible.Trigger
                className={cn('collapsible-frame-header grow max-w-[calc(100%-30px)]', {
                    'cursor-progress': recordLoading,
                })}
                disabled={!hasRecordContext && !recordLoading}
            >
                {functionName && (
                    <span ref={functionRef} className="font-medium frame-function" title={functionName}>
                        {functionName}
                    </span>
                )}
                <span
                    ref={sourceRef}
                    className={cn('font-light frame-source px-1', {
                        'italic text-muted-foreground': isUnsymbolicated,
                    })}
                    title={sourceContent!}
                >
                    {sourceContent}
                </span>
                <div className="gap-x-1 frame-icons">
                    {part && <FingerprintRecordPartDisplay part={part} />}
                    {isUnsymbolicated ? (
                        <UnsymbolicatedIcon
                            in_app={in_app}
                            resolve_failure={resolve_failure}
                            instructionAddress={instructionAddress}
                        />
                    ) : (
                        match([in_app, resolved, recordLoading, hasRecordContext])
                            .with([false, P.any, P.any, P.any], () => <VendorIcon />)
                            .with([true, false, P.any, P.any], () => (
                                <UnresolvedIcon resolve_failure={resolve_failure} />
                            ))
                            .with([true, true, true, false], () => <SpinnerIcon />)
                            .with([true, true, false, false], () => <NoContextIcon lang={lang} raw_id={raw_id} />)
                            .otherwise(() => null)
                    )}
                </div>
            </Collapsible.Trigger>
            <div className="border-l-1 border-l-[color:var(--frame-border,var(--color-border-primary))] shrink-0 w-7">
                <FrameDropDownMenu className="h-full w-7 rounded-none outline-none" frame={frame} record={record}>
                    <IconEllipsis />
                </FrameDropDownMenu>
            </div>
        </div>
    )
}

function FrameWarningIcon({
    title,
    severity,
    docLink,
    resolveFailure,
    children,
}: {
    title: string
    severity: 'error' | 'muted'
    docLink?: string
    resolveFailure?: string | null
    children: ReactNode
}): JSX.Element {
    return (
        <Tooltip
            title={
                <>
                    <h5>{title}</h5>
                    {children}
                    {resolveFailure && <p className="text-xs text-muted-foreground">{resolveFailure}</p>}
                </>
            }
            docLink={docLink}
        >
            <IconWarning className={severity === 'error' ? 'text-red-500' : 'text-muted-foreground'} fontSize={15} />
        </Tooltip>
    )
}

function NoContextIcon({ lang, raw_id }: { lang: string; raw_id: string }): JSX.Element {
    useEffect(() => {
        posthog.capture('error_tracking_frame_missing_content', {
            lang,
            raw_id,
        })
    }, [raw_id, lang])

    return (
        <FrameWarningIcon title="Missing Context" severity="error">
            <p>Frame is resolved but source code is not available.</p>
        </FrameWarningIcon>
    )
}

function UnsymbolicatedIcon({
    in_app,
    resolve_failure,
    instructionAddress,
}: {
    in_app: boolean
    resolve_failure: string | null
    instructionAddress: string | null
}): JSX.Element {
    return (
        <FrameWarningIcon
            title={UNKNOWN_FRAME_LABEL}
            severity={in_app ? 'error' : 'muted'}
            // Symbol sets are only actionable when we have an address to match them against
            docLink={instructionAddress ? SYMBOL_SETS_DOC_LINK : undefined}
            resolveFailure={resolve_failure}
        >
            {instructionAddress ? (
                <>
                    <p>The SDK sent only a memory address for this frame.</p>
                    <p>PostHog couldn't resolve that address to a function or file name.</p>
                </>
            ) : (
                <p>
                    The SDK sent no function name, file name or memory address for this frame, so there is nothing to
                    identify it with.
                </p>
            )}
        </FrameWarningIcon>
    )
}

function SpinnerIcon(): JSX.Element {
    return (
        <Tooltip title="Loading source code...">
            <IconSpinner className="animate-spin text-muted-foreground" fontSize={15} />
        </Tooltip>
    )
}

function VendorIcon(): JSX.Element {
    return (
        <Tooltip title="Vendor frame">
            <IconBox className="text-muted-foreground" fontSize={15} />
        </Tooltip>
    )
}

function UnresolvedIcon({ resolve_failure }: { resolve_failure: string | null }): JSX.Element {
    return (
        <FrameWarningIcon
            title="Unresolved frame"
            severity="muted"
            docLink={SYMBOL_SETS_DOC_LINK}
            resolveFailure={resolve_failure}
        >
            <p>
                Upload your symbol sets to improve issue grouping, see unminified source code and get release
                information.
            </p>
        </FrameWarningIcon>
    )
}

const formatSourceLine = (source: string | null, line: number | null, column: number | null): string | undefined => {
    if (!source) {
        return undefined
    }
    let content = `${source}`
    if (line) {
        content += `@${line}`
        if (column) {
            content += `:${column}`
        }
    }
    return content
}
