import './CollapsibleFrameHeader.scss'

import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'
import { P, match } from 'ts-pattern'

import { IconBox, IconEllipsis, IconSpinner, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { CollapsiblePrimitiveTrigger } from 'lib/ui/CollapsiblePrimitive/CollapsiblePrimitive'
import { cn } from 'lib/utils/css-classes'

import { FingerprintRecordPartDisplay } from '../FingerprintRecordPartDisplay'
import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { formatFunctionName } from '../utils'
import { FrameDropDownMenu } from './FrameDropDownMenu'

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
    const sourceContent = formatSourceLine(source, line, column)

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
        <div className={cn('flex w-full h-7')}>
            <CollapsiblePrimitiveTrigger asChild>
                <ButtonPrimitive
                    className={cn(
                        'collapsible-frame-header flex justify-start items-center rounded-none h-full disabled:opacity-60 grow max-w-[calc(100%-30px)] text-xs p-0 px-2',
                        {
                            'cursor-progress': recordLoading,
                        }
                    )}
                    disabled={!hasRecordContext && !recordLoading}
                >
                    {functionName && (
                        <span ref={functionRef} className="font-medium frame-function" title={functionName}>
                            {functionName}
                        </span>
                    )}
                    <span ref={sourceRef} className="font-light frame-source px-1" title={sourceContent!}>
                        {sourceContent}
                    </span>
                    <div className="gap-x-1 frame-icons">
                        {part && <FingerprintRecordPartDisplay part={part} />}
                        {match([in_app, resolved, recordLoading, hasRecordContext])
                            .with([false, P.any, P.any, P.any], () => <VendorIcon />)
                            .with([true, false, P.any, P.any], () => (
                                <UnresolvedIcon resolve_failure={resolve_failure} />
                            ))
                            .with([true, true, true, false], () => <SpinnerIcon />)
                            .with([true, true, false, false], () => <NoContextIcon lang={lang} raw_id={raw_id} />)
                            .otherwise(() => null)}
                    </div>
                </ButtonPrimitive>
            </CollapsiblePrimitiveTrigger>
            <div className="border-l-1 shrink-0 w-7">
                <FrameDropDownMenu className="h-full w-7 rounded-none outline-none" frame={frame} record={record}>
                    <IconEllipsis />
                </FrameDropDownMenu>
            </div>
        </div>
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
        <Tooltip
            title={
                <>
                    <h5>Missing Context</h5>
                    <p>Frame is resolved but source code is not available.</p>
                </>
            }
        >
            <IconWarning className="text-red-500" fontSize={15} />
        </Tooltip>
    )
}

function SpinnerIcon({}: {}): JSX.Element {
    return (
        <Tooltip title="Loading source code...">
            <IconSpinner className="text-secondary animate-spin" fontSize={15} />
        </Tooltip>
    )
}

function VendorIcon({}: {}): JSX.Element {
    return (
        <Tooltip title="Vendor frame">
            <IconBox className="text-secondary" fontSize={15} />
        </Tooltip>
    )
}

function UnresolvedIcon({ resolve_failure }: { resolve_failure: string | null }): JSX.Element {
    return (
        <Tooltip
            title={
                <>
                    <h5>Unresolved frame</h5>
                    <p>
                        Upload your symbol sets to improve issue grouping, see unminified source code and get release
                        information.
                    </p>
                    <p className="text-xs text-secondary">{resolve_failure}</p>
                </>
            }
            docLink="https://posthog.com/docs/error-tracking/upload-source-maps"
        >
            <IconWarning className="text-secondary" fontSize={15} />
        </Tooltip>
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
