import posthog from 'posthog-js'

import { LemonSelect } from '@posthog/lemon-ui'

import { DurationType } from '~/types'

interface DurationTypeFilterProps {
    // what to call this when reporting analytics to PostHog
    onChangeEventDescription?: string
    onChange: (newFilter: DurationType) => void
    value?: DurationType
}

export function DurationTypeSelect({
    onChange,
    value,
    onChangeEventDescription,
}: DurationTypeFilterProps): JSX.Element {
    return (
        <LemonSelect
            data-attr="duration-type-selector"
            onChange={(v) => {
                posthog.capture(onChangeEventDescription || 'session recording duration type filter changed', {
                    durationChoice: v,
                })
                onChange((v || 'all') as DurationType)
            }}
            options={[
                {
                    label: 'total duration',
                    value: 'duration',
                },
                {
                    label: 'active duration',
                    value: 'active_seconds',
                },
                {
                    label: 'inactive duration',
                    value: 'inactive_seconds',
                },
            ]}
            size="small"
            value={value || 'duration'}
        />
    )
}
