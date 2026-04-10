import './AnnotationsOverlay.scss'

import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { useEffect, useRef, useState } from 'react'

import { IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'

import { Chart } from 'lib/Chart'
import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { dayjs } from 'lib/dayjs'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge/LemonBadge'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { humanFriendlyDetailedTime, pluralize, shortTimeZone } from 'lib/utils'
import { AnnotationModal } from 'scenes/annotations/AnnotationModal'
import { annotationModalLogic, annotationScopeToName } from 'scenes/annotations/annotationModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationType, DatedAnnotationType, IntervalType } from '~/types'

import { AnnotationsOverlayLogicProps, annotationsOverlayLogic } from './annotationsOverlayLogic'
import { useAnnotationsPositioning } from './useAnnotationsPositioning'

/**
 * Minimum pixel spacing between annotation badge centers. Annotation groups whose rendered
 * pixel positions fall within this distance are clustered into a single badge so they don't
 * visually overlap. Tuned to roughly the badge diameter plus a bit of breathing room.
 */
const MIN_BADGE_SPACING_PX = 24

const EMPTY_ANNOTATIONS: DatedAnnotationType[] = []

interface AnnotationBadgeCluster {
    /** Representative date (earliest date in the cluster). Used as the active-state key. */
    date: dayjs.Dayjs
    /** The earliest and latest actual annotation dates in the cluster — for the popover title. */
    dateRange: [dayjs.Dayjs, dayjs.Dayjs]
    /** All annotations from every group merged into this cluster. */
    annotations: DatedAnnotationType[]
    /** Pixel x relative to the overlay (chart plot area). */
    leftPx: number
}

/** User-facing format for annotation groups. Keyed by the grouping unit (not the raw interval),
 * so monthly/weekly charts — which group by day — show full dates in the popover title. */
const GROUPING_UNIT_TO_HUMAN_DAYJS_FORMAT: Record<IntervalType, string> = {
    second: 'MMMM D, YYYY H:mm:ss',
    minute: 'MMMM D, YYYY H:mm:00',
    hour: 'MMMM D, YYYY H:00',
    day: 'MMMM D, YYYY',
    week: 'MMMM D, YYYY',
    month: 'MMMM D, YYYY',
}

/** Linearly interpolate the pixel x for a fractional data-point index. Beyond the last point,
 * extrapolates using the spacing of the previous interval. Returns null when no neighboring
 * points are available (chart not ready). */
function getInterpolatedDataPointX(dataIndex: number, getDataPointX: (index: number) => number | null): number | null {
    const floor = Math.floor(dataIndex)
    const fraction = dataIndex - floor
    const xFloor = getDataPointX(floor)
    if (xFloor === null) {
        return null
    }
    if (fraction === 0) {
        return xFloor
    }
    const xNext = getDataPointX(floor + 1)
    if (xNext !== null) {
        return xFloor + fraction * (xNext - xFloor)
    }
    const xPrev = getDataPointX(floor - 1)
    if (xPrev !== null) {
        return xFloor + fraction * (xFloor - xPrev)
    }
    return xFloor
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
}

export const AnnotationsOverlay = React.memo(function AnnotationsOverlay({
    chart,
    chartWidth,
    chartHeight,
    dates,
    insightNumericId,
}: AnnotationsOverlayProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { tickIntervalPx, firstTickLeftPx, getDataPointX } = useAnnotationsPositioning(chart, chartWidth, chartHeight)

    // Memoize ticks by value to prevent unnecessary kea selector cascades.
    // chart.scales.x.ticks is a Chart.js internal array that is the same object between renders
    // when the chart hasn't changed, but .map() would create new references every render,
    // causing all downstream selectors (tickDates → dateRange → relevantAnnotations →
    // groupedAnnotations) to recompute unnecessarily.
    const prevTicksRef = useRef<{ value: number }[]>([])
    const currentChartTicks = chart.scales.x.ticks
    if (
        prevTicksRef.current.length !== currentChartTicks.length ||
        prevTicksRef.current.some((t, i) => t.value !== currentChartTicks[i]?.value)
    ) {
        prevTicksRef.current = currentChartTicks.map(({ value }) => ({ value }))
    }

    const annotationsOverlayLogicProps: AnnotationsOverlayLogicProps = {
        ...insightProps,
        dashboardId: insightProps.dashboardId,
        insightNumericId,
        dates,
        ticks: prevTicksRef.current,
    }
    const logic = annotationsOverlayLogic(annotationsOverlayLogicProps)
    const { activeDate, tickDates, annotationBadgeDataIndices, groupedAnnotations } = useValues(logic)
    const { closePopover } = useActions(logic)
    const { closeModal } = useActions(annotationModalLogic)

    useEffect(() => {
        return () => {
            closePopover()
            closeModal()
        }
    }, [closePopover, closeModal])

    const overlayRef = useRef<HTMLDivElement | null>(null)
    const modalContentRef = useRef<HTMLDivElement | null>(null)
    const modalOverlayRef = useRef<HTMLDivElement | null>(null)
    const badgeRefs = useRef<Map<string, HTMLButtonElement>>(new Map())
    const chartAreaLeft = chart ? chart.scales.x.left : 0

    // Cluster annotation badges whose pixel positions would visually overlap. Each cluster
    // becomes a single badge with a merged annotation list and a date range.
    const clusters = React.useMemo<AnnotationBadgeCluster[]>(() => {
        const positioned = annotationBadgeDataIndices
            .map(({ dateKey, date, dataIndex }) => {
                const absoluteX = getInterpolatedDataPointX(dataIndex, getDataPointX)
                if (absoluteX === null) {
                    return null
                }
                return {
                    dateKey,
                    date,
                    leftPx: absoluteX - chartAreaLeft,
                    annotations: groupedAnnotations[dateKey] || [],
                }
            })
            .filter((b): b is NonNullable<typeof b> => b !== null)
            .sort((a, b) => a.leftPx - b.leftPx)

        const out: AnnotationBadgeCluster[] = []
        for (const badge of positioned) {
            const last = out[out.length - 1]
            if (last && badge.leftPx - last.leftPx < MIN_BADGE_SPACING_PX) {
                last.annotations = [...last.annotations, ...badge.annotations]
                last.dateRange = [last.dateRange[0], badge.date]
                // Keep the first badge's leftPx as the cluster anchor — prevents jitter when
                // additional badges join and keeps the badge visually pinned to a data point.
            } else {
                out.push({
                    date: badge.date,
                    dateRange: [badge.date, badge.date],
                    annotations: badge.annotations,
                    leftPx: badge.leftPx,
                })
            }
        }
        return out
    }, [annotationBadgeDataIndices, getDataPointX, chartAreaLeft, groupedAnnotations])

    // Map: cluster key (representative date ISO string) → cluster. Used by the popover to
    // look up its annotations and date range from the active badge.
    const clusterByKey = React.useMemo(() => {
        const m = new Map<string, AnnotationBadgeCluster>()
        clusters.forEach((c) => m.set(c.date.toISOString(), c))
        return m
    }, [clusters])

    const activeBadgeElement = activeDate ? badgeRefs.current.get(activeDate.toISOString()) : undefined
    const activeCluster = activeDate ? clusterByKey.get(activeDate.toISOString()) : undefined

    return (
        <BindLogic logic={annotationsOverlayLogic} props={annotationsOverlayLogicProps}>
            <div
                className="AnnotationsOverlay"
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--annotations-overlay-chart-area-left': `${chartAreaLeft}px`,
                        '--annotations-overlay-chart-area-height': `${chart ? chart.scales.x.top : 0}px`,
                        '--annotations-overlay-chart-width': `${chartWidth}px`,
                    } as AnnotationsOverlayCSSProperties
                }
                ref={overlayRef}
            >
                {/* Add-annotation targets: one per chart tick, invisible until hovered.
                    Skipped when too close to a rendered cluster badge to prevent overlap. */}
                {tickDates.map((date, index) => {
                    const leftPx = index * tickIntervalPx + firstTickLeftPx - chartAreaLeft
                    const overlapsCluster = clusters.some((c) => Math.abs(c.leftPx - leftPx) < MIN_BADGE_SPACING_PX)
                    if (overlapsCluster) {
                        return null
                    }
                    return (
                        <AnnotationsBadge
                            key={`tick-${date.toISOString()}`}
                            date={date}
                            leftPx={leftPx}
                            widthPx={tickIntervalPx}
                            annotations={EMPTY_ANNOTATIONS}
                            badgeRefs={badgeRefs}
                        />
                    )
                })}
                {/* Cluster badges: merged from nearby annotation groups. Hit area is narrow so
                    adjacent badges don't swallow each other's clicks. */}
                {clusters.map((cluster) => (
                    <AnnotationsBadge
                        key={`cluster-${cluster.date.toISOString()}`}
                        date={cluster.date}
                        leftPx={cluster.leftPx}
                        widthPx={MIN_BADGE_SPACING_PX}
                        annotations={cluster.annotations}
                        badgeRefs={badgeRefs}
                    />
                ))}
                {activeBadgeElement && (
                    <AnnotationsPopover
                        overlayRefs={[overlayRef, modalContentRef, modalOverlayRef]}
                        badgeElement={activeBadgeElement}
                        cluster={activeCluster}
                    />
                )}
                <AnnotationModal
                    contentRef={(el) => (modalContentRef.current = el)}
                    overlayRef={(el) => (modalOverlayRef.current = el)}
                />
            </div>
        </BindLogic>
    )
})

interface AnnotationsBadgeProps {
    date: dayjs.Dayjs
    /** Pixel offset from the left of the overlay (which starts at the chart's plot area). */
    leftPx: number
    /** Hit area width in pixels. Tick add-targets use the full tick interval so users can hover
     *  anywhere along the tick to add an annotation; cluster badges use a narrow width to avoid
     *  swallowing clicks intended for neighboring badges. */
    widthPx: number
    /** Annotations to show in this badge. Empty array for tick add-targets. */
    annotations: DatedAnnotationType[]
    badgeRefs: React.MutableRefObject<Map<string, HTMLButtonElement>>
}

interface AnnotationsBadgeCSSProperties extends React.CSSProperties {
    '--annotations-badge-left': string
    '--annotations-badge-width': string
    '--annotations-badge-scale': number
}

const AnnotationsBadge = React.memo(function AnnotationsBadgeRaw({
    date,
    leftPx,
    widthPx,
    annotations,
    badgeRefs,
}: AnnotationsBadgeProps): JSX.Element {
    const { isDateLocked, activeDate, isPopoverShown } = useValues(annotationsOverlayLogic)
    const { activateDate, deactivateDate, lockDate, unlockDate } = useActions(annotationsOverlayLogic)

    const [hovered, setHovered] = useState(false)
    const buttonRef = useRef<HTMLButtonElement>(null)
    const dateKey = date.toISOString()

    useEffect(() => {
        const el = buttonRef.current
        if (el) {
            badgeRefs.current.set(dateKey, el)
        }
        return () => {
            badgeRefs.current.delete(dateKey)
        }
    }, [dateKey, badgeRefs])

    const active = activeDate?.valueOf() === date.valueOf() && isPopoverShown
    const shown = active || hovered || annotations.length > 0

    return (
        <button
            ref={buttonRef}
            className="AnnotationsBadge"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--annotations-badge-left': `${leftPx}px`,
                    '--annotations-badge-width': `${widthPx}px`,
                    '--annotations-badge-scale': shown ? 1 : 0,
                } as AnnotationsBadgeCSSProperties
            }
            onMouseEnter={() => {
                setHovered(true)
                if (!isDateLocked) {
                    activateDate(date)
                }
            }}
            onMouseLeave={() => {
                setHovered(false)
                if (!isDateLocked) {
                    deactivateDate()
                }
            }}
            onClick={!isDateLocked ? lockDate : active ? unlockDate : () => activateDate(date)}
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
    badgeElement,
    cluster,
}: {
    overlayRefs: React.MutableRefObject<HTMLDivElement | null>[]
    badgeElement: HTMLButtonElement | null
    cluster: AnnotationBadgeCluster | undefined
}): JSX.Element {
    const { activeDate, groupingUnit, isDateLocked, insightId, isPopoverShown, annotationsOverlayProps } =
        useValues(annotationsOverlayLogic)
    const { closePopover } = useActions(annotationsOverlayLogic)
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)

    // An empty cluster means the active badge is a tick add-target — no annotations to show,
    // only the "add annotation" affordance.
    const popoverAnnotations = cluster?.annotations ?? []

    // Capture event when popup is shown with a system annotation
    useEffect(() => {
        if (
            isPopoverShown &&
            popoverAnnotations.some((annotation: AnnotationType) => annotation.id === -1 || annotation.id === -2)
        ) {
            posthog.capture('person_property_incident_annotation_viewed', {
                annotation_count: popoverAnnotations.length,
                has_system_annotation: true,
            })
        }
    }, [isPopoverShown, popoverAnnotations])

    const titleDate = (() => {
        if (!cluster) {
            return activeDate?.format(GROUPING_UNIT_TO_HUMAN_DAYJS_FORMAT[groupingUnit])
        }
        const [from, to] = cluster.dateRange
        const format = GROUPING_UNIT_TO_HUMAN_DAYJS_FORMAT[groupingUnit]
        if (from.valueOf() === to.valueOf()) {
            return from.format(format)
        }
        return `${from.format(format)} – ${to.format(format)}`
    })()

    return (
        <Popover
            additionalRefs={overlayRefs}
            className="AnnotationsPopover"
            placement="top"
            fallbackPlacements={['top-end', 'top-start']}
            referenceElement={badgeElement}
            visible={isPopoverShown}
            onClickOutside={closePopover}
            showArrow
            padded={false}
            overlay={
                <LemonModal
                    inline
                    title={`${pluralize(popoverAnnotations.length, 'annotation')} • ${titleDate}`}
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

    const isSystemAnnotation = annotation.id === -1 || annotation.id === -2

    return (
        <li
            className={`AnnotationCard flex flex-col w-full p-3 rounded border list-none ${
                isSystemAnnotation ? 'border-primary/30 bg-primary/5' : ''
            }`}
        >
            <div className="flex items-center gap-2">
                <h5 className="grow m-0 text-secondary">
                    {annotation.date_marker?.format('MMM DD, YYYY h:mm A')} ({shortTimeZone(timezone)}) –{' '}
                    {annotationScopeToName[annotation.scope]}
                    -level
                </h5>
                {!isSystemAnnotation && (
                    <>
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
                    </>
                )}
            </div>
            <div className="mt-1 flex items-center gap-3">
                {isSystemAnnotation && (
                    <LemonBadge status="primary" size="small" className="flex-shrink-0" content="PostHog" />
                )}
                <TextContent text={annotation.content ?? ''} data-attr="annotation-overlay-rendered-content" />
            </div>
            {!isSystemAnnotation && (
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
                </div>
            )}
        </li>
    )
}
