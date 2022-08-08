import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils'
import React from 'react'
import { InstanceSetting } from '~/types'
import { MetricRow } from './systemStatusLogic'
import { IconLock } from 'lib/components/icons'

const TIMESTAMP_VALUES = new Set(['last_event_ingested_timestamp'])

type BaseValueInterface = Pick<MetricRow, 'key' | 'value'> & Partial<Pick<InstanceSetting, 'value_type'>>
export interface MetricValueInterface extends BaseValueInterface {
    emptyNullLabel?: string
    isSecret?: boolean
}

export function RenderMetricValue({
    key,
    value,
    value_type,
    emptyNullLabel,
    isSecret,
}: MetricValueInterface): JSX.Element | string {
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

    if (TIMESTAMP_VALUES.has(key) && typeof value === 'string') {
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
