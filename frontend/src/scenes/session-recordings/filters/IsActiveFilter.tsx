import { LemonSelect } from '@posthog/lemon-ui'
import { IsSessionRecordingActiveFilter } from '~/types'

interface IsActiveFilterProps {
    onChange: (newFilter: IsSessionRecordingActiveFilter) => void
    initialFilter?: IsSessionRecordingActiveFilter
}

export function IsActiveFilter({ onChange, initialFilter }: IsActiveFilterProps): JSX.Element {
    return (
        <LemonSelect
            onChange={(v) => onChange((v || 'all') as IsSessionRecordingActiveFilter)}
            options={[
                {
                    label: 'All sessions',
                    value: 'all',
                },
                {
                    label: 'Only active sessions',
                    value: 'include',
                },
                {
                    label: 'Only inactive sessions',
                    value: 'exclude',
                },
            ]}
            size="small"
            value={initialFilter || 'all'}
        />
    )
}
