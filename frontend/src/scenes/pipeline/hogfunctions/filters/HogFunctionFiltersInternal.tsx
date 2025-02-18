import { LemonSelect } from '@posthog/lemon-ui'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { HogFunctionFiltersType } from '~/types'

// NOTE: This is all a bit WIP and will be improved upon over time
// TODO: Make this more advanced with sub type filtering etc.
// TODO: Make it possible for the renderer to limit the options based on the type
const FILTER_OPTIONS = [
    {
        label: 'Team activity',
        value: '$activity_log_entry_created',
    },
    {
        label: 'Error tracking issue created',
        value: '$error_tracking_issue_created',
    },
]

const getSimpleFilterValue = (value?: HogFunctionFiltersType): string | undefined => {
    return value?.events?.[0]?.id
}

const setSimpleFilterValue = (value: string): HogFunctionFiltersType => {
    return {
        events: [
            {
                name: FILTER_OPTIONS.find((option) => option.value === value)?.label,
                id: value,
                type: 'events',
            },
        ],
    }
}

export function HogFunctionFiltersInternal({ templateId }: { templateId?: string }): JSX.Element {
    const options = templateId?.includes('error-tracking')
        ? FILTER_OPTIONS.filter((o) => o.value.includes('$error_tracking'))
        : FILTER_OPTIONS

    return (
        <div className="p-3 space-y-2 border rounded bg-surface-primary">
            <LemonField name="filters" label="Trigger" help="Choose what event should trigger this destination">
                {({ value, onChange }) => (
                    <>
                        <LemonSelect
                            options={options}
                            value={getSimpleFilterValue(value)}
                            onChange={(value) => onChange(setSimpleFilterValue(value))}
                            placeholder="Select a filter"
                        />
                    </>
                )}
            </LemonField>
        </div>
    )
}
