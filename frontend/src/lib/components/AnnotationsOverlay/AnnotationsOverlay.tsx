import './AnnotationsOverlay.scss'

import { IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'
import { BindLogic, useActions, useValues } from 'kea'
import { Chart } from 'lib/Chart'
import { dayjs } from 'lib/dayjs'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge/LemonBadge'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { humanFriendlyDetailedTime, pluralize, shortTimeZone } from 'lib/utils'
import React, { useRef, useState } from 'react'
import { AnnotationModal } from 'scenes/annotations/AnnotationModal'
import { annotationModalLogic, annotationScopeToName } from 'scenes/annotations/annotationModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationScope, AnnotationType, IntervalType } from '~/types'

import {
    annotationsOverlayLogic,
    AnnotationsOverlayLogicProps,
    determineAnnotationsDateGroup,
} from './annotationsOverlayLogic'
import { useAnnotationsPositioning } from './useAnnotationsPositioning'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'

/** User-facing format for annotation groups. */
const INTERVAL_UNIT_TO_HUMAN_DAYJS_FORMAT: Record<IntervalType, string> = {
    minute: 'MMMM D, YYYY H:mm:00',
    hour: 'MMMM D, YYYY H:00',
    day: 'MMMM D, YYYY',
    week: '[Week of] MMMM D, YYYY',
    month: 'MMMM D',
}

export interface AnnotationsOverlayProps {
    insightNumericId: AnnotationsOverlayLogicProps['insightNumericId']
    dates: string[]
    chart: Chart
    chartWidth: number
    chartHeight: number
}

interface AnnotationsOverlayCSSProperties extends React.CSSProperties {
    '--annotations-overlay-chart-area-left': `${string}px`
    '--annotations-overlay-chart-area-height': `${string}px`
    '--annotations-overlay-chart-width': `${string}px`
    '--annotations-overlay-first-tick-left': `${string}px`
    '--annotations-overlay-tick-interval': `${string}px`
}

export function AnnotationsOverlay({
    chart,
    chartWidth,
    chartHeight,
    dates,
    insightNumericId,
}: AnnotationsOverlayProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { tickIntervalPx, firstTickLeftPx } = useAnnotationsPositioning(chart, chartWidth, chartHeight)

    // FIXME: This pollutes insightProps with dates and ticks, which is not ideal
    const annotationsOverlayLogicProps: AnnotationsOverlayLogicProps = {
        ...insightProps,
        dashboardId: insightProps.dashboardId,
        insightNumericId,
        dates,
        ticks: chart.scales.x.ticks,
    }
    const { activeBadgeElement, tickDates } = useValues(annotationsOverlayLogic(annotationsOverlayLogicProps))

    const overlayRef = useRef<HTMLDivElement | null>(null)
    const modalContentRef = useRef<HTMLDivElement | null>(null)
    const modalOverlayRef = useRef<HTMLDivElement | null>(null)

    return (
        <BindLogic logic={annotationsOverlayLogic} props={annotationsOverlayLogicProps}>
            <div
                className="AnnotationsOverlay"
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--annotations-overlay-chart-area-left': `${chart ? chart.scales.x.left : 0}px`,
                        '--annotations-overlay-chart-area-height': `${chart ? chart.scales.x.top : 0}px`,
                        '--annotations-overlay-chart-width': `${chartWidth}px`,
                        '--annotations-overlay-first-tick-left': `${firstTickLeftPx}px`,
                        '--annotations-overlay-tick-interval': `${tickIntervalPx}px`,
                    } as AnnotationsOverlayCSSProperties
                }
                ref={overlayRef}
            >
                {tickDates.map((date, index) => (
                    <AnnotationsBadge key={date.toISOString()} index={index} date={date} />
                ))}
                {activeBadgeElement && (
                    <AnnotationsPopover overlayRefs={[overlayRef, modalContentRef, modalOverlayRef]} />
                )}
                <AnnotationModal
                    contentRef={(el) => (modalContentRef.current = el)}
                    overlayRef={(el) => (modalOverlayRef.current = el)}
                />
            </div>
        </BindLogic>
    )
}

interface AnnotationsBadgeProps {
    index: number
    date: dayjs.Dayjs
}

interface AnnotationsBadgeCSSProperties extends React.CSSProperties {
    '--annotations-badge-index': number
    '--annotations-badge-scale': number
}

const AnnotationsBadge = React.memo(function AnnotationsBadgeRaw({ index, date }: AnnotationsBadgeProps): JSX.Element {
    const { intervalUnit, groupedAnnotations, isDateLocked, activeDate, isPopoverShown, dateRange, pointsPerTick } =
        useValues(annotationsOverlayLogic)
    const { activateDate, deactivateDate, lockDate, unlockDate } = useActions(annotationsOverlayLogic)

    const [hovered, setHovered] = useState(false)
    const buttonRef = useRef<HTMLButtonElement>(null)

    const dateGroup = determineAnnotationsDateGroup(date, intervalUnit, dateRange, pointsPerTick)
    const annotations = groupedAnnotations[dateGroup] || []

    const active = activeDate?.valueOf() === date.valueOf() && isPopoverShown
    const shown = active || hovered || annotations.length > 0

    return (
        <button
            ref={buttonRef}
            className="AnnotationsBadge"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--annotations-badge-index': index,
                    '--annotations-badge-scale': shown ? 1 : 0,
                } as AnnotationsBadgeCSSProperties
            }
            onMouseEnter={() => {
                setHovered(true)
                if (!isDateLocked) {
                    activateDate(date, buttonRef.current as HTMLButtonElement)
                }
            }}
            onMouseLeave={() => {
                setHovered(false)
                if (!isDateLocked) {
                    deactivateDate()
                }
            }}
            onClick={
                !isDateLocked
                    ? lockDate
                    : active
                    ? unlockDate
                    : () => activateDate(date, buttonRef.current as HTMLButtonElement)
            }
        >
            {annotations.length ? (
                <LemonBadge.Number
                    count={annotations.length}
                    status="data"
                    size="small"
                    active={active && isDateLocked}
                />
            ) : (
                <LemonBadge content={<IconPlusSmall />} status="data" size="small" active={active && isDateLocked} />
            )}
        </button>
    )
})

function AnnotationsPopover({
    overlayRefs,
}: {
    overlayRefs: React.MutableRefObject<HTMLDivElement | null>[]
}): JSX.Element {
    const {
        popoverAnnotations,
        activeDate,
        intervalUnit,
        isDateLocked,
        insightId,
        activeBadgeElement,
        isPopoverShown,
        annotationsOverlayProps,
    } = useValues(annotationsOverlayLogic)
    const { closePopover } = useActions(annotationsOverlayLogic)
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)

    return (
        <Popover
            additionalRefs={overlayRefs}
            className="AnnotationsPopover"
            placement="top"
            fallbackPlacements={['top-end', 'top-start']}
            referenceElement={activeBadgeElement as HTMLElement}
            visible={isPopoverShown}
            onClickOutside={closePopover}
            showArrow
            padded={false}
            overlay={
                <LemonModal
                    inline
                    title={`${pluralize(popoverAnnotations.length, 'annotation')} • ${activeDate?.format(
                        INTERVAL_UNIT_TO_HUMAN_DAYJS_FORMAT[intervalUnit]
                    )}`}
                    footer={
                        <LemonButton
                            type="primary"
                            onClick={() =>
                                openModalToCreateAnnotation(activeDate, insightId, annotationsOverlayProps.dashboardId)
                            }
                            disabled={!isDateLocked}
                        >
                            Add annotation
                        </LemonButton>
                    }
                    closable={isDateLocked}
                    onClose={closePopover}
                    width="var(--annotations-popover-width)"
                >
                    {popoverAnnotations.length > 0 ? (
                        <ul className="flex flex-col gap-2 w-full overflow-y-auto">
                            {popoverAnnotations.map((annotation) => (
                                <AnnotationCard key={annotation.id} annotation={annotation} />
                            ))}
                        </ul>
                    ) : (
                        'There are no annotations in this period.'
                    )}
                </LemonModal>
            }
        />
    )
}

function AnnotationCard({ annotation }: { annotation: AnnotationType }): JSX.Element {
    const { insightId, timezone, annotationsOverlayProps } = useValues(annotationsOverlayLogic)
    const { deleteAnnotation } = useActions(annotationsModel)
    const { openModalToEditAnnotation } = useActions(annotationModalLogic)

    return (
        <li className="AnnotationCard flex flex-col w-full p-3 rounded border list-none">
            <div className="flex items-center gap-2">
                <h5 className="grow m-0 text-secondary">
                    {annotation.date_marker?.format('MMM DD, YYYY h:mm A')} ({shortTimeZone(timezone)}) –{' '}
                    {annotationScopeToName[annotation.scope]}
                    {annotation.scope === AnnotationScope.Recording ? ' comment' : '-level'}
                </h5>
                <LemonButton
                    size="small"
                    icon={<IconPencil />}
                    tooltip="Edit this annotation"
                    onClick={() =>
                        openModalToEditAnnotation(annotation, insightId, annotationsOverlayProps.dashboardId)
                    }
                    noPadding
                />
                <LemonButton
                    size="small"
                    icon={<IconTrash />}
                    tooltip="Delete this annotation"
                    onClick={() => deleteAnnotation(annotation)}
                    noPadding
                />
            </div>
            <div className="mt-1">{annotation.content}</div>
            <div className="leading-6 mt-2 flex flex-row items-center justify-between">
                <div>
                    <ProfilePicture
                        user={
                            annotation.creation_type === 'GIT'
                                ? { first_name: 'GitHub automation' }
                                : annotation.created_by
                        }
                        showName
                        size="md"
                        type={annotation.creation_type === 'GIT' ? 'bot' : 'person'}
                    />{' '}
                    • {humanFriendlyDetailedTime(annotation.created_at, 'MMMM DD, YYYY', 'h:mm A')}
                </div>
                {annotation.scope === AnnotationScope.Recording &&
                !!annotation.recording_id &&
                !!annotation.date_marker ? (
                    <ViewRecordingButton
                        sessionId={annotation.recording_id}
                        timestamp={annotation.date_marker}
                        inModal={true}
                    />
                ) : null}
            </div>
        </li>
    )
}
