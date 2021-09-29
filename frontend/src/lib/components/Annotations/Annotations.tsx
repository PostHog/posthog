import React from 'react'
import dayjs from 'dayjs'
import { annotationsLogic } from './annotationsLogic'
import { useValues, useActions } from 'kea'
import { AnnotationMarker } from './AnnotationMarker'
import { AnnotationType, AnnotationScope } from '~/types'

interface AnnotationsProps {
    dates: string[]
    leftExtent: number
    interval: number
    topExtent: number
    dashboardItemId?: number
    color: string | null
    graphColor: string
    accessoryColor: string | null
    currentDateMarker: string
    onClick: () => void
    onClose: () => void
}

export function Annotations({
    dates,
    leftExtent,
    interval,
    topExtent,
    dashboardItemId,
    onClick,
    color,
    accessoryColor,
    onClose,
    graphColor,
    currentDateMarker,
}: AnnotationsProps): JSX.Element[] {
    const { diffType, groupedAnnotations } = useValues(
        annotationsLogic({
            pageKey: dashboardItemId ? dashboardItemId : null,
        })
    )

    const { createAnnotation, createAnnotationNow, deleteAnnotation, deleteGlobalAnnotation, createGlobalAnnotation } =
        useActions(
            annotationsLogic({
                pageKey: dashboardItemId ? dashboardItemId : null,
            })
        )

    const markers: JSX.Element[] = []
    dates &&
        dates.forEach((date: string, index: number) => {
            const annotations =
                groupedAnnotations[
                    dayjs(date)
                        .startOf(diffType as dayjs.OpUnitType)
                        .format('YYYY-MM-DD')
                ]
            if (annotations) {
                markers.push(
                    <AnnotationMarker
                        elementId={dates[index]}
                        label={dayjs(dates[index]).format('MMMM Do YYYY')}
                        key={index}
                        left={index * interval + leftExtent - 12.5}
                        top={topExtent}
                        annotations={annotations}
                        onCreate={(input: string, applyAll: boolean) => {
                            if (applyAll) {
                                createGlobalAnnotation(input, dates[index], dashboardItemId)
                            } else if (dashboardItemId) {
                                createAnnotationNow(input, dates[index])
                            } else {
                                createAnnotation(input, dates[index])
                            }
                        }}
                        onDelete={(data: AnnotationType) => {
                            annotations.length === 1 && onClose?.()
                            if (data.scope !== AnnotationScope.DashboardItem) {
                                deleteGlobalAnnotation(data.id)
                            } else {
                                deleteAnnotation(data.id)
                            }
                        }}
                        onClick={onClick}
                        onClose={onClose}
                        color={color}
                        graphColor={graphColor}
                        accessoryColor={accessoryColor}
                        currentDateMarker={currentDateMarker}
                        index={index}
                    />
                )
            }
        })
    return markers
}
