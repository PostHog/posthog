import { LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { INSIGHT_ALERT_DESTINATION_LOGIC_KEY } from 'scenes/insights/InsightAlertDestinationScene'

import { HogFunctionFiltersType } from '~/types'

import { hogFunctionConfigurationLogic, HogFunctionConfigurationLogicProps } from '../hogFunctionConfigurationLogic'

type FilterOption = { value: string; label: string }

// NOTE: This is all a bit WIP and will be improved upon over time
// TODO: Make this more advanced with sub type filtering etc.
// TODO: Make it possible for the renderer to limit the options based on the type
const getFilterOptions = (logicKey?: HogFunctionConfigurationLogicProps['logicKey']): FilterOption[] => {
    if (logicKey && logicKey === 'errorTracking') {
        return [
            {
                label: 'Error tracking issue created',
                value: '$error_tracking_issue_created',
            },
            {
                label: 'Error tracking issue reopened',
                value: '$error_tracking_issue_reopened',
            },
        ]
    }
    if (logicKey && logicKey === INSIGHT_ALERT_DESTINATION_LOGIC_KEY) {
        return [
            {
                label: 'Insight alert firing',
                value: '$insight_alert_firing',
            },
        ]
    }
    return [
        {
            label: 'Team activity',
            value: '$activity_log_entry_created',
        },
    ]
}

const getSimpleFilterValue = (value?: HogFunctionFiltersType): string | undefined => {
    return value?.events?.[0]?.id
}

const setSimpleFilterValue = (options: FilterOption[], value: string): HogFunctionFiltersType => {
    return {
        events: [
            {
                name: options.find((option) => option.value === value)?.label,
                id: value,
                type: 'events',
            },
        ],
    }
}

export function HogFunctionFiltersInternal(): JSX.Element {
    const { logicProps } = useValues(hogFunctionConfigurationLogic)

    const options = getFilterOptions(logicProps.logicKey)

    return (
        <div className="p-3 deprecated-space-y-2 border rounded bg-surface-primary">
            <LemonField name="filters" label="Trigger" help="Choose what event should trigger this destination">
                {({ value, onChange }) => (
                    <>
                        <LemonSelect
                            options={options}
                            value={getSimpleFilterValue(value)}
                            onChange={(value) => onChange(setSimpleFilterValue(options, value))}
                            placeholder="Select a filter"
                        />
                    </>
                )}
            </LemonField>
        </div>
    )
}
