import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'
import { P, match } from 'ts-pattern'

import { IconBox, IconEllipsis, IconSpinner, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { CollapsiblePrimitiveTrigger } from 'lib/ui/CollapsiblePrimitive/CollapsiblePrimitive'
import { cn } from 'lib/utils/css-classes'

import { FingerprintRecordPartDisplay } from '../FingerprintRecordPartDisplay'
import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { formatResolvedName } from '../utils'
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
    const resolvedName = formatResolvedName(frame)
    const hasRecordContext = !!record && !!record.context

    return (
        <div className={cn('flex justify-between items-center w-full h-7')}>
            <CollapsiblePrimitiveTrigger asChild>
                <ButtonPrimitive
                    className={cn(
                        'flex justify-between items-center rounded-none w-full h-full gap-x-10 disabled:opacity-60',
                        {
                            'cursor-progress': recordLoading,
                        }
                    )}
                    disabled={!hasRecordContext && !recordLoading}
                >
                    <div className="flex flex-wrap gap-x-1 items-center text-xs w-full min-w-0">
                        {resolvedName ? (
                            <div className="flex min-w-0 font-medium">
                                <span className="truncate" title={resolvedName}>
                                    {resolvedName}
                                </span>
                            </div>
                        ) : null}
                        <div className="flex font-light">
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
            <div className="border-r-1 w-0 h-full" />
            <FrameDropDownMenu className="h-full w-7 rounded-none outline-none" frame={frame} record={record}>
                <IconEllipsis />
            </FrameDropDownMenu>
        </div>
    )
}

function NoContextIcon({ lang, raw_id }: { lang: string; raw_id: string }): JSX.Element {
    useEffect(() => {
        posthog.capture('error_tracking_frame_missing_content', {
            lang,
            raw_id,
        })
    }, [])

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
