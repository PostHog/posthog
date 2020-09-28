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
    graphColor,
    currentDateMarker,
}) {
    const { diffType, groupedAnnotations } = useValues(
        annotationsLogic({
            pageKey: dashboardItemId ? dashboardItemId : null,
        })
    )

    const {
        createAnnotation,
        createAnnotationNow,
        deleteAnnotation,
        deleteGlobalAnnotation,
        createGlobalAnnotation,
    } = useActions(
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
                    elementId={dates[index]}
                    label={moment(dates[index]).format('MMMM Do YYYY')}
                    key={index}
                    left={index * interval + leftExtent - 12.5}
                    top={topExtent}
                    annotations={annotations}
                    onCreate={(input, applyAll) => {
                        if (applyAll) createGlobalAnnotation(input, dates[index], dashboardItemId)
                        else if (dashboardItemId) createAnnotationNow(input, dates[index])
                        else createAnnotation(input, dates[index])
                    }}
                    onDelete={(data) => {
                        annotations.length === 1 && onClose?.()
                        if (data.scope !== 'dashboard_item') deleteGlobalAnnotation(data.id)
                        else deleteAnnotation(data.id)
                    }}
                    onClick={onClick}
                    onClose={onClose}
                    color={color}
                    graphColor={graphColor}
                    accessoryColor={accessoryColor}
                    currentDateMarker={currentDateMarker}
                    index={index}
                ></AnnotationMarker>
            )
        }
    })
    return markers
}
