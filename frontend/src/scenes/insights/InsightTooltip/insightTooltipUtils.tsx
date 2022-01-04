import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { ActionFilter, CompareLabelType } from '~/types'

export interface SeriesDatum {
    id: number
    dataIndex: number
    datasetIndex: number
    breakdown_value?: string | number
    compare_value?: CompareLabelType
    action?: ActionFilter
    color: string
    count: number
}

export interface InvertedSeriesDatum {
    id: number
    color: string
    datumTitle: React.ReactNode
    seriesData: SeriesDatum[]
}

export function getFormattedDate(dayString?: string): string {
    const day = dayjs(dayString)
    if (dayString !== undefined && day.isValid()) {
        return day.format('DD MMM YYYY')
    }
    return 'Date'
}

export function invertDataSource(seriesData: SeriesDatum[]): InvertedSeriesDatum[] {
    const flattenedData = {}
    seriesData.forEach((s) => {
        let datumTitle
        if (s.breakdown_value && s.compare_value) {
            datumTitle = (
                <>
                    {capitalizeFirstLetter(String(s.breakdown_value))}{' '}
                    <span className="sub-datum-title">{s.compare_value}</span>
                </>
            )
        } else if (!s.breakdown_value && s.compare_value) {
            datumTitle = capitalizeFirstLetter(s.compare_value)
        } else if (!s.compare_value && s.breakdown_value) {
            datumTitle = capitalizeFirstLetter(String(s.breakdown_value))
        } else {
            // Technically should never reach this point because series data should have at least breakdown or compare values
            datumTitle = 'Baseline'
        }
        const datumKey = `${s.breakdown_value}-${s.compare_value}`
        if (datumKey in flattenedData) {
            flattenedData[datumKey].seriesData.push(s)
        } else {
            flattenedData[datumKey] = {
                id: datumKey,
                color: s.color,
                datumTitle,
                seriesData: [s],
            }
        }
    })
    return Object.values(flattenedData)
}
