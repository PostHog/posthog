import { useValues } from 'kea'
import { Fragment, useMemo, useState } from 'react'

import { IconBox, IconChevronRight } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { CollapsibleExceptionHeader } from '../Exception/CollapsibleExceptionHeader'
import { ExceptionRenderer } from '../Exception/ExceptionRenderer'
import { CollapsibleFrame } from '../Frame/CollapsibleFrame'
import { EmptyStackTrace } from '../StackTrace/EmptyStackTrace'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { ExceptionListRenderer } from './ExceptionListRenderer'

type StackFrameGroup =
    | { type: 'frame'; frame: ErrorTrackingStackFrame }
    | { type: 'vendor'; key: string; frames: ErrorTrackingStackFrame[]; expandedByDefault?: boolean }

function groupStackFrames(
    frames: ErrorTrackingStackFrame[],
    exceptionId: string,
    options: { expandSingleVendorGroupByDefault: boolean }
): StackFrameGroup[] {
    const groups: StackFrameGroup[] = []
    let vendorFrames: ErrorTrackingStackFrame[] = []
    let vendorGroupIndex = 0

    const flushVendorFrames = (): void => {
        if (vendorFrames.length === 0) {
            return
        }
        groups.push({
            type: 'vendor',
            key: `${exceptionId}:vendor:${vendorGroupIndex}`,
            frames: vendorFrames,
        })
        vendorFrames = []
        vendorGroupIndex += 1
    }

    for (const frame of frames) {
        if (frame.in_app) {
            flushVendorFrames()
            groups.push({ type: 'frame', frame })
            continue
        }
        vendorFrames.push(frame)
    }

    flushVendorFrames()
    if (options.expandSingleVendorGroupByDefault && groups.length === 1 && groups[0].type === 'vendor') {
        groups[0].expandedByDefault = true
    }
    return groups
}

function GroupedStackTraceRenderer({
    frames,
    exceptionId,
    expandSingleVendorGroupByDefault,
    stackFrameRecords,
    renderFrame,
    renderVendorFrameGroup,
}: {
    frames: ErrorTrackingStackFrame[]
    exceptionId: string
    expandSingleVendorGroupByDefault: boolean
    stackFrameRecords: Record<string, ErrorTrackingStackFrameRecord | undefined>
    renderFrame: (frame: ErrorTrackingStackFrame, record?: ErrorTrackingStackFrameRecord) => React.ReactNode
    renderVendorFrameGroup: (group: Extract<StackFrameGroup, { type: 'vendor' }>) => React.ReactNode
}): JSX.Element {
    const frameGroups = useMemo(
        () => groupStackFrames(frames, exceptionId, { expandSingleVendorGroupByDefault }),
        [exceptionId, expandSingleVendorGroupByDefault, frames]
    )

    return (
        <div className="border-1 rounded overflow-hidden divide-y divide-solid">
            {frameGroups.map((group) => (
                <Fragment key={group.type === 'frame' ? group.frame.raw_id : group.key}>
                    {group.type === 'frame'
                        ? renderFrame(group.frame, stackFrameRecords[group.frame.raw_id])
                        : renderVendorFrameGroup(group)}
                </Fragment>
            ))}
        </div>
    )
}

export function CollapsibleExceptionList({
    className,
    expandedFrameRawIds,
    onFrameExpandedChange,
}: {
    expandedFrameRawIds: Set<string>
    onFrameExpandedChange: (rawId: string, expanded: boolean) => void
    className?: string
}): JSX.Element {
    const [expandedVendorFrameGroups, setExpandedVendorFrameGroups] = useState<Record<string, boolean>>({})
    const { exceptionList, getExceptionFingerprint, exceptionAttributes, stackFrameRecords, stackFrameRecordsLoading } =
        useValues(errorPropertiesLogic)

    const toggleVendorFrameGroup = (group: Extract<StackFrameGroup, { type: 'vendor' }>): void => {
        setExpandedVendorFrameGroups((previous) => {
            const expanded = previous[group.key] ?? !!group.expandedByDefault
            return { ...previous, [group.key]: !expanded }
        })
    }

    const renderFrame = (
        exception: { id: string },
        frame: ErrorTrackingStackFrame,
        record?: ErrorTrackingStackFrameRecord
    ): JSX.Element => {
        const expansionKey = `${exception.id}:${frame.raw_id}`

        return (
            <CollapsibleFrame
                frame={frame}
                record={record}
                recordLoading={stackFrameRecordsLoading}
                expanded={expandedFrameRawIds.has(expansionKey)}
                onExpandedChange={(open) => onFrameExpandedChange(expansionKey, open)}
            />
        )
    }

    const renderVendorFrameGroup = (group: Extract<StackFrameGroup, { type: 'vendor' }>): JSX.Element => {
        const expanded = expandedVendorFrameGroups[group.key] ?? !!group.expandedByDefault
        const frameCount = group.frames.length

        return (
            <>
                <button
                    type="button"
                    className="flex w-full items-center justify-center gap-2 px-3 py-2 text-xs text-muted hover:text-primary hover:bg-fill-button-tertiary-hover"
                    onClick={() => toggleVendorFrameGroup(group)}
                >
                    <IconBox className="size-3 shrink-0" />
                    <span>
                        {expanded ? 'Hide' : 'Show'} {frameCount} vendor {frameCount === 1 ? 'frame' : 'frames'}
                    </span>
                    <IconChevronRight className={cn('size-3 shrink-0 transition-transform', expanded && 'rotate-90')} />
                </button>
                {expanded &&
                    group.frames.map((frame) => (
                        <div key={frame.raw_id}>
                            {renderFrame({ id: group.key }, frame, stackFrameRecords[frame.raw_id])}
                        </div>
                    ))}
            </>
        )
    }

    return (
        <div className={cn('flex flex-col gap-y-2', className)}>
            <ExceptionListRenderer
                exceptionList={exceptionList}
                renderException={(exception, exceptionIndex) => {
                    const exceptionKey = `${exception.id}:${exceptionIndex}`
                    const part = getExceptionFingerprint(exception.id)
                    return (
                        <ExceptionRenderer
                            exception={exception}
                            renderExceptionHeader={(exception) => (
                                <CollapsibleExceptionHeader
                                    exception={exception}
                                    loading={false}
                                    fingerprint={part}
                                    runtime={exceptionAttributes?.runtime}
                                />
                            )}
                            renderResolvedTrace={(frames: ErrorTrackingStackFrame[]) => (
                                <GroupedStackTraceRenderer
                                    frames={frames}
                                    exceptionId={exceptionKey}
                                    expandSingleVendorGroupByDefault={exceptionIndex === 0}
                                    stackFrameRecords={stackFrameRecords}
                                    renderFrame={(frame, record) => renderFrame(exception, frame, record)}
                                    renderVendorFrameGroup={renderVendorFrameGroup}
                                />
                            )}
                            renderUndefinedTrace={(exception, known) => (
                                <EmptyStackTrace exception={exception} knownException={known} />
                            )}
                        />
                    )
                }}
            />
        </div>
    )
}
