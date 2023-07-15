import { LemonSelect } from '@posthog/lemon-ui'
import { DurationType } from '~/types'

interface DurationTypeFilterProps {
    onChange: (newFilter: DurationType) => void
    value?: DurationType
}

export function DurationTypeSelect({ onChange, value }: DurationTypeFilterProps): JSX.Element {
    return (
        <LemonSelect
            data-attr="duration-type-selector"
            onChange={(v) => onChange((v || 'all') as DurationType)}
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
