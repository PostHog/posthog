import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { MetricRow } from './systemStatusLogic'

const TIMESTAMP_VALUES = new Set(['last_event_ingested_timestamp'])

export function RenderMetricValue({ key, value }: Pick<MetricRow, 'key' | 'value'>): JSX.Element | string {
    if (TIMESTAMP_VALUES.has(key)) {
        if (new Date(value).getTime() === new Date('1970-01-01T00:00:00').getTime()) {
            return 'Never'
        }
        return humanFriendlyDetailedTime(value)
    }

    if (typeof value === 'boolean') {
        return <LemonTag type={value ? 'success' : 'danger'}>{value ? 'Yes' : 'No'}</LemonTag>
    }

    if (value === null || value === undefined || value === '') {
        return <LemonTag>Unknown</LemonTag>
    }

    return value.toString()
}
