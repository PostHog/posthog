import React from 'react'
import moment from 'moment'
import { annotationsLogic } from './annotationsLogic'
import { useValues, useActions } from 'kea'
import { AnnotationMarker } from './AnnotationMarker'

export const Annotations = function Annotations({
    dates,
    leftExtent,
    interval,
    topExtent,
    dashboardItemId,
    onClick,
    color,
    accessoryColor,
    onClose,
}) {
    const { diffType, groupedAnnotations } = useValues(
        annotationsLogic({
            pageKey: dashboardItemId ? dashboardItemId : null,
        })
    )

    const { createAnnotation, createAnnotationNow, deleteAnnotation } = useActions(
        annotationsLogic({
            pageKey: dashboardItemId ? dashboardItemId : null,
        })
    )

    const markers = []
    dates.forEach((date, index) => {
        const annotations = groupedAnnotations[moment(date).startOf(diffType)]
        if (annotations) {
            markers.push(
                <AnnotationMarker
                    label={moment(dates[index]).format('MMMM Do YYYY')}
                    key={index}
                    left={index * interval + leftExtent - 12.5}
                    top={topExtent}
                    annotations={annotations}
                    onCreate={(input, applyAll) => {
                        dashboardItemId
                            ? createAnnotationNow(input, dates[index], applyAll)
                            : createAnnotation(input, dates[index], applyAll)
                    }}
                    onDelete={(id) => {
                        deleteAnnotation(id)
                        onClose?.()
                    }}
                    onClick={onClick}
                    onClose={onClose}
                    color={color}
                    accessoryColor={accessoryColor}
                ></AnnotationMarker>
            )
        }
    })
    return markers
}
