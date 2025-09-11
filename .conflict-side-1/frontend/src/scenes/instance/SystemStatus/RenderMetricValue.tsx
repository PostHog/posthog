import { IconLock } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

import { InstanceSetting, SystemStatusRow } from '~/types'

const TIMESTAMP_VALUES = new Set(['last_event_ingested_timestamp'])

export interface MetricValue {
    key: SystemStatusRow['key']
    value?: SystemStatusRow['value']
    value_type?: InstanceSetting['value_type']
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
                className="uppercase text-secondary bg-mark"
                icon={isSecret ? <IconLock className="text-warning" /> : undefined}
            >
                Secret
            </LemonTag>
        )
    }

    if (key && TIMESTAMP_VALUES.has(key) && typeof value === 'string') {
        if (new Date(value).getTime() === new Date('1970-01-01T00:00:00').getTime()) {
            return 'Never'
        }
        return <TZLabel time={value} />
    }

    if (value_type === 'bool' || typeof value === 'boolean') {
        return (
            <LemonTag className="uppercase" type={value ? 'success' : 'danger'}>
                {value ? 'Yes' : 'No'}
            </LemonTag>
        )
    }

    if (value === null || value === undefined || value === '') {
        return <LemonTag className="uppercase text-secondary">{emptyNullLabel ?? 'Unknown'}</LemonTag>
    }

    if (value_type === 'int' || typeof value === 'number') {
        return value.toLocaleString('en-US')
    }

    return value.toString()
}
