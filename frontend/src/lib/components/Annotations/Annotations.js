import React, { useState, useEffect } from 'react'
import moment from 'moment'
import { annotationsModel } from '~/models'
import { useValues, useActions } from 'kea'
import { AnnotationMarker } from './AnnotationMarker'

export const Annotations = React.memo(function Annotations({
    labeledDates,
    leftExtent,
    interval,
    topExtent,
    dashboardItemId,
}) {
    const [groupedAnnotations, setGroupedAnnotations] = useState({})
    const [diffType, setDiffType] = useState(determineDifferenceType(labeledDates[0], labeledDates[1]))
    const { annotationsList } = useValues(annotationsModel({ pageKey: dashboardItemId ? dashboardItemId : null }))

    const { createAnnotation, createAnnotationNow, deleteAnnotation } = useActions(
        annotationsModel({ pageKey: dashboardItemId ? dashboardItemId : null })
    )

    useEffect(() => {
        // calculate groups
        setDiffType(determineDifferenceType(labeledDates[0], labeledDates[1]))
        let groupedResults = _.groupBy(annotationsList, annote => moment(annote['date_marker']).startOf(diffType))
        setGroupedAnnotations(groupedResults)
    }, [annotationsList, labeledDates])

    const markers = []
    labeledDates.forEach((date, index) => {
        const annotations = groupedAnnotations[moment(date).startOf(diffType)]
        if (annotations) {
            markers.push(
                <AnnotationMarker
                    key={index}
                    left={index * interval + leftExtent - 15}
                    top={topExtent}
                    annotations={annotations}
                    onCreate={input => {
                        dashboardItemId
                            ? createAnnotationNow(input, labeledDates[index])
                            : createAnnotation(input, labeledDates[index])
                    }}
                    onDelete={id => deleteAnnotation(id)}
                ></AnnotationMarker>
            )
        }
    })
    return markers
})

function determineDifferenceType(firstDate, secondDate) {
    const first = moment(firstDate)
    const second = moment(secondDate)
    if (first.diff(second, 'years') !== 0) return 'year'
    else if (first.diff(second, 'months') !== 0) return 'month'
    else if (first.diff(second, 'weeks') !== 0) return 'week'
    else if (first.diff(second, 'days') !== 0) return 'day'
    else if (first.diff(second, 'hours') !== 0) return 'hour'
    else return 'minute'
}
