import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { InstanceSetting, SystemStatusRow } from '~/types'
import { IconLock } from 'lib/components/icons'

const TIMESTAMP_VALUES = new Set(['last_event_ingested_timestamp'])

type BaseMetricValue = Pick<SystemStatusRow, 'key' | 'value'> & Partial<Pick<InstanceSetting, 'value_type'>>
export interface MetricValue extends BaseMetricValue {
    emptyNullLabel?: string
    isSecret?: boolean
}

export function RenderMetricValue(
    _: any,
    { key, value, value_type, emptyNullLabel, isSecret }: MetricValue
): JSX.Element | string {
    if (value && isSecret) {
        return (
            <LemonTag
                style={{ color: 'var(--muted)', backgroundColor: '#fee5b3' }}
                icon={isSecret ? <IconLock style={{ color: 'var(--warning)' }} /> : undefined}
            >
                Secret
            </LemonTag>
        )
    }

    if (key && TIMESTAMP_VALUES.has(key) && typeof value === 'string') {
        if (new Date(value).getTime() === new Date('1970-01-01T00:00:00').getTime()) {
            return 'Never'
        }
        return humanFriendlyDetailedTime(value)
    }

    if (value_type === 'bool' || typeof value === 'boolean') {
        return <LemonTag type={value ? 'success' : 'danger'}>{value ? 'Yes' : 'No'}</LemonTag>
    }

    if (value === null || value === undefined || value === '') {
        return <LemonTag style={{ color: 'var(--muted)' }}>{emptyNullLabel ?? 'Unknown'}</LemonTag>
    }

    if (value_type === 'int' || typeof value === 'number') {
        return value.toLocaleString('en-US')
    }

    return value.toString()
}
