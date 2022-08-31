import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import React, { useState } from 'react'
import { AnnotationType } from '~/types'
import { IconPlusMini } from '../icons'
import { LemonBubble } from '../LemonBubble/LemonBubble'
import './AnnotationsOverlay.scss'
import { ANNOTATIONS_INTERVAL_UNIT_TO_DAYJS_FORMAT, insightAnnotationsLogic } from './insightAnnotationsLogic'

export interface AnnotationsOverlayProps {
    dates: dayjs.Dayjs[] | undefined
}

export function AnnotationsOverlay({ dates }: AnnotationsOverlayProps): JSX.Element {
    const { intervalUnit, groupedAnnotations } = useValues(insightAnnotationsLogic)

    return (
        <div className="AnnotationsOverlay">
            {dates?.map((date, index) => (
                <AnnotationsBadge
                    key={date.toISOString()}
                    index={index}
                    date={date}
                    annotations={
                        groupedAnnotations[date.format(ANNOTATIONS_INTERVAL_UNIT_TO_DAYJS_FORMAT[intervalUnit])] || []
                    }
                />
            ))}
        </div>
    )
}

interface AnnotationsBadgeProps {
    index: number
    date: dayjs.Dayjs
    annotations: AnnotationType[]
}

interface AnnotationsOverlayCSSProperties extends React.CSSProperties {
    '--annotations-badge-index': number
    '--annotations-badge-scale': number
}

function AnnotationsBadge({ index, annotations }: AnnotationsBadgeProps): JSX.Element {
    const [isHoveredOver, setIsHoveredOver] = useState(false)

    return (
        <div
            className="AnnotationsBadge"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--annotations-badge-index': index,
                    '--annotations-badge-scale': annotations.length || isHoveredOver ? 1 : 0,
                } as AnnotationsOverlayCSSProperties
            }
            onMouseEnter={() => setIsHoveredOver(true)}
            onMouseLeave={() => setIsHoveredOver(false)}
        >
            <LemonBubble
                count={annotations.length}
                showZero={<IconPlusMini className="w-full h-full" />}
                size="small"
            />
        </div>
    )
}
