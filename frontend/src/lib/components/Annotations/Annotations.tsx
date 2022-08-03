import React from 'react'
import { annotationsLogic } from './annotationsLogic'
import { useValues, useActions } from 'kea'
import { AnnotationMarker } from './AnnotationMarker'
import { AnnotationType, AnnotationScope } from '~/types'
import { dayjs } from 'lib/dayjs'

interface AnnotationsProps {
    dates: string[]
    leftExtent: number
    interval: number
    topExtent: number
    insightNumericId?: number
    color: string | null
    accessoryColor: string | null
    currentDateMarker?: string | null
    onClick: () => void
    onClose: () => void
}

export function Annotations({
    dates,
    leftExtent,
    interval,
    topExtent,
    insightNumericId,
    onClick,
    color,
    accessoryColor,
    onClose,
    currentDateMarker,
}: AnnotationsProps): JSX.Element {
    const logic = annotationsLogic({ insightNumericId })
    const { diffType, groupedAnnotations } = useValues(logic)
    const { createAnnotation, deleteAnnotation, deleteGlobalAnnotation, createGlobalAnnotation } = useActions(logic)

    const onCreate =
        (date: string) =>
        (input: string, applyAll: boolean): void => {
            if (applyAll) {
                createGlobalAnnotation(input, date, insightNumericId)
            } else {
                createAnnotation(input, date)
            }
        }

    const markers: JSX.Element[] = []

    const makeAnnotationMarker = (index: number, date: string, annotationsToMark: AnnotationType[]): JSX.Element => (
        <AnnotationMarker
            insightNumericId={insightNumericId}
            elementId={date}
            label={dayjs(date).format('MMMM Do YYYY')}
            key={index}
            left={index * interval + leftExtent - 12.5}
            top={topExtent}
            annotations={annotationsToMark}
            onCreate={onCreate(date)}
            onDelete={(data: AnnotationType) => {
                annotationsToMark.length === 1 && onClose?.()
                if (data.scope !== AnnotationScope.Insight) {
                    deleteGlobalAnnotation(data.id)
                } else {
                    deleteAnnotation(data.id)
                }
            }}
            onClick={onClick}
            onClose={onClose}
            color={color}
            accessoryColor={accessoryColor}
            currentDateMarker={currentDateMarker}
            index={index}
        />
    )

    const filterAnnotations = (annotations: AnnotationType[], dateKey: string, index: number): void => {
        annotations.forEach((annotation) => {
            if (annotation.date_marker.startsWith(dateKey)) {
                markers.push(makeAnnotationMarker(index, dates[index], [annotation]))
            }
        })
    }

    dates &&
        dates.forEach((date: string, index: number) => {
            const chosenTime = dayjs(date).startOf(diffType as dayjs.OpUnitType)
            const groupedAnnotationKey = chosenTime.format('YYYY-MM-DD')
            const annotations = groupedAnnotations[groupedAnnotationKey] || []

            if (diffType === 'minute') {
                const minuteKey = chosenTime.format('YYYY-MM-DDTHH:mm')
                filterAnnotations(annotations, minuteKey, index)
            } else if (diffType === 'hour') {
                const hourKey = chosenTime.format('YYYY-MM-DDTHH')
                filterAnnotations(annotations, hourKey, index)
            } else if (annotations.length) {
                markers.push(makeAnnotationMarker(index, dates[index], annotations))
            }
        })
    return <>{markers}</>
}
