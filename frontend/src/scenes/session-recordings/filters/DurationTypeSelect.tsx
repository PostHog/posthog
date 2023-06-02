import { LemonSelect } from '@posthog/lemon-ui'
import { DurationTypeFilter } from '~/types'

interface DurationTypeFilterProps {
    onChange: (newFilter: DurationTypeFilter) => void
    value?: DurationTypeFilter
}

export function DurationTypeSelect({ onChange, value }: DurationTypeFilterProps): JSX.Element {
    return (
        <LemonSelect
            onChange={(v) => onChange((v || 'all') as DurationTypeFilter)}
            options={[
                {
                    label: 'total duration',
                    value: 'duration',
                },
                {
                    label: 'active duration',
                    value: 'active_seconds',
                },
            ]}
            size="small"
            value={value || 'duration'}
        />
    )
}
