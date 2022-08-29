import React from 'react'
import { insightAnnotationsLogic } from './insightAnnotationsLogic'
import { useValues, useActions } from 'kea'
import { AnnotationMarker } from './AnnotationMarker'
import { AnnotationType, AnnotationScope } from '~/types'
import { dayjs } from 'lib/dayjs'

interface AnnotationsProps {
    dates: string[]
    leftExtent: number
    interval: number
    topExtent: number
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
    onClick,
    color,
    accessoryColor,
    onClose,
    currentDateMarker,
}: AnnotationsProps): JSX.Element {
    // insightAnnotationsLogic must be bound using BindLogic
    const { intervalUnit, groupedAnnotations } = useValues(insightAnnotationsLogic)
    const { createAnnotation, deleteAnnotation } = useActions(insightAnnotationsLogic)

    const onCreate =
        (date: string) =>
        (input: string, applyAll: boolean): void => {
            createAnnotation({
                content: input,
                date_marker: date,
                scope: applyAll ? AnnotationScope.Project : AnnotationScope.Insight,
            })
        }

    const markers: JSX.Element[] = []

    const makeAnnotationMarker = (index: number, date: string, annotationsToMark: AnnotationType[]): JSX.Element => (
        <AnnotationMarker
            elementId={date}
            label={dayjs(date).format('MMMM Do YYYY')}
            key={index}
            left={index * interval + leftExtent - 12.5}
            top={topExtent}
            annotations={annotationsToMark}
            onCreate={onCreate(date)}
            onDelete={(annotationToDelete: AnnotationType) => {
                annotationsToMark.length === 1 && onClose?.()
                deleteAnnotation(annotationToDelete)
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
            const chosenTime = dayjs(date).startOf(intervalUnit)
            const groupedAnnotationKey = chosenTime.format('YYYY-MM-DD')
            const annotations = groupedAnnotations[groupedAnnotationKey] || []

            if (intervalUnit === 'hour') {
                const hourKey = chosenTime.format('YYYY-MM-DDTHH')
                filterAnnotations(annotations, hourKey, index)
            } else if (annotations.length) {
                markers.push(makeAnnotationMarker(index, dates[index], annotations))
            }
        })
    return <>{markers}</>
}
