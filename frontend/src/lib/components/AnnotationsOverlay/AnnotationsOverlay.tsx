import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'
import React, { useRef, useState } from 'react'
import { AnnotationType, IntervalType } from '~/types'
import { IconLock, IconPlusMini } from '../icons'
import { LemonBubble } from '../LemonBubble/LemonBubble'
import { LemonModal } from '../LemonModal'
import { annotationsOverlayLogic, determineAnnotationsDateGroup } from './annotationsOverlayLogic'
import './AnnotationsOverlay.scss'
import { LemonButton } from '../LemonButton'
import { AnnotationModal } from 'scenes/annotations/AnnotationModal'
import { annotationModalLogic } from 'scenes/annotations/annotationModalLogic'

/** Useer-facing format for annotation groups. */
const INTERVAL_UNIT_TO_HUMAN_DAYJS_FORMAT: Record<IntervalType, string> = {
    hour: 'MMMM D, YYYY h:00',
    day: 'MMMM D, YYYY',
    week: 'Week of MMMM D, YYYY',
    month: 'MMMM D',
}

export interface AnnotationsOverlayProps {
    dates: dayjs.Dayjs[] | undefined
}

interface AnnotationsOverlayCSSProperties extends React.CSSProperties {
    '--annotations-overlay-active-badge-left': string
    '--annotations-overlay-active-badge-top': string
}

export function AnnotationsOverlay({ dates }: AnnotationsOverlayProps): JSX.Element {
    const { activeDate, activeBadgeCoordinates } = useValues(annotationsOverlayLogic)

    return (
        <div
            className="AnnotationsOverlay"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                activeBadgeCoordinates
                    ? ({
                          '--annotations-overlay-active-badge-left': `${activeBadgeCoordinates[0]}px`,
                          '--annotations-overlay-active-badge-top': `${activeBadgeCoordinates[1]}px`,
                      } as AnnotationsOverlayCSSProperties)
                    : undefined
            }
        >
            {dates?.map((date, index) => (
                <AnnotationsBadge key={date.toISOString()} index={index} date={date} active={date === activeDate} />
            ))}
            {activeDate && <AnnotationsPopover />}
            <AnnotationModal />
        </div>
    )
}

interface AnnotationsBadgeProps {
    index: number
    date: dayjs.Dayjs
    active: boolean
}

interface AnnotationsBadgeCSSProperties extends React.CSSProperties {
    '--annotations-badge-index': number
    '--annotations-badge-scale': number
}

const AnnotationsBadge = React.memo(function AnnotationsBadgeRaw({
    index,
    date,
    active,
}: AnnotationsBadgeProps): JSX.Element {
    const { intervalUnit, groupedAnnotations, isDateLocked } = useValues(annotationsOverlayLogic)
    const { activateDate, deactivateDate, lockDate } = useActions(annotationsOverlayLogic)

    const [hovered, setHovered] = useState(false)
    const buttonRef = useRef<HTMLButtonElement>(null)

    const dateGroup = determineAnnotationsDateGroup(date, intervalUnit)
    const annotations = groupedAnnotations[dateGroup] || []

    return (
        <button
            ref={buttonRef}
            className="AnnotationsBadge"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--annotations-badge-index': index,
                    '--annotations-badge-scale': annotations.length || hovered || active ? 1 : 0,
                } as AnnotationsBadgeCSSProperties
            }
            onMouseEnter={() => {
                setHovered(true)
                if (!isDateLocked) {
                    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
                    activateDate(date, [buttonRef.current!.offsetLeft, buttonRef.current!.offsetTop])
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
                    : () => {
                          // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
                          activateDate(date, [buttonRef.current!.offsetLeft, buttonRef.current!.offsetTop])
                      }
            }
        >
            <LemonBubble
                count={
                    active && isDateLocked ? (
                        <IconLock />
                    ) : (
                        annotations.length || <IconPlusMini className="w-full h-full" />
                    )
                }
                size="small"
            />
        </button>
    )
})

function AnnotationsPopover(): JSX.Element {
    const { popoverAnnotations, activeDate, intervalUnit, isDateLocked } = useValues(annotationsOverlayLogic)
    const { unlockDate } = useActions(annotationsOverlayLogic)
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)

    return (
        <LemonModal
            className="AnnotationsPopover"
            inline
            title={`${pluralize(popoverAnnotations.length, 'annotation')} • ${activeDate?.format(
                INTERVAL_UNIT_TO_HUMAN_DAYJS_FORMAT[intervalUnit]
            )}`}
            footer={
                <>
                    <LemonButton
                        type="primary"
                        onClick={() => openModalToCreateAnnotation(activeDate)}
                        disabled={!isDateLocked}
                    >
                        Add annotation
                    </LemonButton>
                </>
            }
            closable={isDateLocked}
            onClose={unlockDate}
        >
            {popoverAnnotations.map((annotation) => (
                <AnnotationCard key={annotation.id} annotation={annotation} />
            ))}
        </LemonModal>
    )
}

function AnnotationCard({ annotation }: { annotation: AnnotationType }): JSX.Element {
    return <div>{annotation.content}</div>
}
