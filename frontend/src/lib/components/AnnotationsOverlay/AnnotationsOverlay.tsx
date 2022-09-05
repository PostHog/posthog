import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime, pluralize } from 'lib/utils'
import React, { useRef, useState } from 'react'
import { AnnotationScope, IntervalType, AnnotationType } from '~/types'
import { IconDelete, IconEdit, IconPlusMini } from '../icons'
import { LemonBubble } from '../LemonBubble/LemonBubble'
import { LemonModal } from '../LemonModal'
import { annotationsOverlayLogic, determineAnnotationsDateGroup } from './annotationsOverlayLogic'
import './AnnotationsOverlay.scss'
import { LemonButton } from '../LemonButton'
import { AnnotationModal } from 'scenes/annotations/AnnotationModal'
import { annotationModalLogic } from 'scenes/annotations/annotationModalLogic'
import { ProfilePicture } from '../ProfilePicture'
import { CSSTransition } from 'react-transition-group'
import { annotationsModel } from '~/models/annotationsModel'
import { Chart } from 'chart.js'
import { useAnnotationsPositioning } from './useAnnotationsPositioning'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'

/** User-facing format for annotation groups. */
const INTERVAL_UNIT_TO_HUMAN_DAYJS_FORMAT: Record<IntervalType, string> = {
    hour: 'MMMM D, YYYY H:00',
    day: 'MMMM D, YYYY',
    week: '[Week of] MMMM D, YYYY',
    month: 'MMMM D',
}

export const annotationScopeToLabel: Record<AnnotationScope, string> = {
    [AnnotationScope.Insight]: 'Only this insight',
    [AnnotationScope.Project]: 'All insights in this project',
    [AnnotationScope.Organization]: 'All insights in this organization',
}

export interface AnnotationsOverlayProps {
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
    '--annotations-overlay-active-badge-left'?: `${string}px`
    '--annotations-overlay-active-badge-top'?: `${string}px`
}

export function AnnotationsOverlay({ chart, chartWidth, chartHeight }: AnnotationsOverlayProps): JSX.Element {
    const { isPopoverShown, activeBadgeCoordinates } = useValues(annotationsOverlayLogic)
    const { closePopover } = useActions(annotationsOverlayLogic)
    const { tickIntervalPx, firstTickLeftPx } = useAnnotationsPositioning(chart, chartWidth, chartHeight)

    const overlayRef = useRef<HTMLDivElement>(null)
    const modalContentRef = useRef<HTMLDivElement | null>(null)
    const modalOverlayRef = useRef<HTMLDivElement | null>(null)

    useOutsideClickHandler([overlayRef, modalContentRef, modalOverlayRef], () => closePopover())

    const dates: dayjs.Dayjs[] = chart.scales.x.ticks.map(({ label }) => {
        return dayjs(label as string)
    })

    return (
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
                    ...(activeBadgeCoordinates
                        ? {
                              '--annotations-overlay-active-badge-left': `${activeBadgeCoordinates[0]}px`,
                              '--annotations-overlay-active-badge-top': `${activeBadgeCoordinates[1]}px`,
                          }
                        : {}),
                } as AnnotationsOverlayCSSProperties
            }
            ref={overlayRef}
        >
            {dates?.map((date, index) => (
                <AnnotationsBadge key={date.toISOString()} index={index} date={date} />
            ))}
            {/* FIXME: Fix appear animation to be smooth too */}
            <CSSTransition
                in={isPopoverShown}
                timeout={200}
                classNames="AnnotationsPopover-"
                mountOnEnter
                unmountOnExit
            >
                <AnnotationsPopover />
            </CSSTransition>
            <AnnotationModal
                contentRef={(el) => (modalContentRef.current = el)}
                overlayRef={(el) => (modalOverlayRef.current = el)}
            />
        </div>
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
    const { intervalUnit, groupedAnnotations, isDateLocked, activeDate, isPopoverShown } =
        useValues(annotationsOverlayLogic)
    const { activateDate, deactivateDate, lockDate, unlockDate } = useActions(annotationsOverlayLogic)

    const [hovered, setHovered] = useState(false)
    const buttonRef = useRef<HTMLButtonElement>(null)

    const dateGroup = determineAnnotationsDateGroup(date, intervalUnit)
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
                    const button = buttonRef.current as HTMLButtonElement
                    activateDate(date, [button.offsetLeft, button.offsetTop])
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
                    : () => {
                          const button = buttonRef.current as HTMLButtonElement
                          activateDate(date, [button.offsetLeft, button.offsetTop])
                      }
            }
        >
            <LemonBubble
                count={annotations.length || <IconPlusMini className="w-full h-full" />}
                size="small"
                style={active && isDateLocked ? { outline: '0.125rem solid var(--primary)' } : undefined}
            />
        </button>
    )
})

function AnnotationsPopover(): JSX.Element {
    const { popoverAnnotations, activeDate, intervalUnit, isDateLocked, insightId } = useValues(annotationsOverlayLogic)
    const { closePopover } = useActions(annotationsOverlayLogic)
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)

    return (
        <div className="AnnotationsPopover">
            <LemonModal
                inline
                title={`${pluralize(popoverAnnotations.length, 'annotation')} • ${activeDate?.format(
                    INTERVAL_UNIT_TO_HUMAN_DAYJS_FORMAT[intervalUnit]
                )}`}
                footer={
                    <LemonButton
                        type="primary"
                        onClick={() => openModalToCreateAnnotation(activeDate, insightId)}
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
                    <ul className="flex flex-col gap-1 w-full overflow-y-auto m-0 p-0">
                        {popoverAnnotations.map((annotation) => (
                            <AnnotationCard key={annotation.id} annotation={annotation} />
                        ))}
                    </ul>
                ) : (
                    'There are no annotations in this period.'
                )}
            </LemonModal>
        </div>
    )
}

function AnnotationCard({ annotation }: { annotation: AnnotationType }): JSX.Element {
    const { insightId } = useValues(annotationsOverlayLogic)
    const { deleteAnnotation } = useActions(annotationsModel)
    const { openModalToEditAnnotation } = useActions(annotationModalLogic)

    return (
        <li className="AnnotationCard flex flex-col gap-2 w-full p-3 rounded border list-none">
            <div className="flex items-center gap-2">
                <h5 className="grow m-0 text-muted">{annotationScopeToLabel[annotation.scope]}</h5>
                <LemonButton
                    size="small"
                    icon={<IconEdit />}
                    status="muted"
                    tooltip="Edit this annotation"
                    onClick={() => openModalToEditAnnotation(annotation, insightId)}
                />
                <LemonButton
                    size="small"
                    icon={<IconDelete />}
                    status="muted"
                    tooltip="Delete this annotation"
                    onClick={() => deleteAnnotation(annotation)}
                />
            </div>
            <div>{annotation.content}</div>
            <div className="leading-6">
                <ProfilePicture
                    name={annotation.created_by?.first_name}
                    email={annotation.created_by?.email}
                    showName
                    size="md"
                />{' '}
                • {humanFriendlyDetailedTime(annotation.created_at)}
            </div>
        </li>
    )
}
