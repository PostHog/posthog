import { dayjs } from 'lib/dayjs'
import React from 'react'
import { ActionFilter, CompareLabelType } from '~/types'
import { Space, Tag, Typography } from 'antd'
import { capitalizeFirstLetter, midEllipsis, pluralize } from 'lib/utils'

export interface SeriesDatum {
    id: number
    dataIndex: number
    datasetIndex: number
    breakdown_value?: string | number
    compare_label?: CompareLabelType
    action?: ActionFilter
    dotted?: boolean
    color?: string
    count: number
}

export interface InvertedSeriesDatum {
    id: string
    datasetIndex: number
    color?: string
    datumTitle: React.ReactNode
    seriesData: SeriesDatum[]
}

export function getFormattedDate(dayInput?: string | number): string {
    // Number of days
    if (Number.isInteger(dayInput)) {
        return pluralize(dayInput as number, 'day')
    }
    const day = dayjs(dayInput)
    // Dayjs formatted day
    if (dayInput !== undefined && day.isValid()) {
        return day.format('DD MMM YYYY')
    }
    return String(dayInput)
}

export function invertDataSource(seriesData: SeriesDatum[]): InvertedSeriesDatum[] {
    const flattenedData: Record<string, InvertedSeriesDatum> = {}
    seriesData.forEach((s) => {
        let datumTitle
        const pillValues = []
        if (s.breakdown_value !== undefined) {
            pillValues.push(String(s.breakdown_value || 'None'))
        }
        if (s.compare_label) {
            pillValues.push(capitalizeFirstLetter(String(s.compare_label)))
        }
        if (pillValues.length > 0) {
            datumTitle = (
                <Space direction={'horizontal'} wrap={true} align="center">
                    {pillValues.map((pill) => (
                        <Tag className="tag-pill" key={pill} closable={false}>
                            <Typography.Text ellipsis={{ tooltip: pill }} style={{ maxWidth: 150 }}>
                                {midEllipsis(pill, 30)}
                            </Typography.Text>
                        </Tag>
                    ))}
                </Space>
            )
        } else {
            // Technically should never reach this point because series data should have at least breakdown or compare values
            datumTitle = 'Baseline'
        }
        const datumKey = `${s.breakdown_value}-${s.compare_label}`
        if (datumKey in flattenedData) {
            flattenedData[datumKey].seriesData.push(s)
        } else {
            flattenedData[datumKey] = {
                id: datumKey,
                datasetIndex: s.datasetIndex,
                color: s.color,
                datumTitle,
                seriesData: [s],
            }
        }
    })
    return Object.values(flattenedData)
}
