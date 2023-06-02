import { LemonSelect } from '@posthog/lemon-ui'
import { DurationFilterType } from '~/types'

interface DurationTypeFilterProps {
    onChange: (newFilter: DurationFilterType) => void
    initialFilter?: DurationFilterType
}

export function DurationTypeFilter({ onChange, initialFilter }: DurationTypeFilterProps): JSX.Element {
    return (
        <LemonSelect
            onChange={(v) => onChange((v || 'all') as DurationFilterType)}
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
            value={initialFilter || 'duration'}
        />
    )
}
