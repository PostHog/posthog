import React, { useState, useEffect } from 'react'
import moment from 'moment'
import { annotationsLogic } from './annotationsLogic'
import { useValues, useActions } from 'kea'
import { AnnotationMarker } from './AnnotationMarker'
import _ from 'lodash'

export const Annotations = React.memo(function Annotations({
    dates,
    labeledDays,
    leftExtent,
    interval,
    topExtent,
    dashboardItemId,
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
                    label={labeledDays[index]}
                    key={index}
                    left={index * interval + leftExtent - 12.5}
                    top={topExtent}
                    annotations={annotations}
                    onCreate={input => {
                        dashboardItemId
                            ? createAnnotationNow(input, dates[index])
                            : createAnnotation(input, dates[index])
                    }}
                    onDelete={id => deleteAnnotation(id)}
                ></AnnotationMarker>
            )
        }
    })
    return markers
})
