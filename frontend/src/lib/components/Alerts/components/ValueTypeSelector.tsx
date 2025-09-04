import { Group } from 'kea-forms'

import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { ValueType } from '~/queries/schema/schema-general'

export interface ValueTypeSelectorProps {
    value?: ValueType
    onChange: (value: ValueType) => void
}

export function ValueTypeSelector({ value, onChange }: ValueTypeSelectorProps): JSX.Element {
    return (
        <div className="flex gap-4 items-center">
            <div>On</div>
            <Group name={['detector_config']}>
                <LemonField name="value_type">
                    <Tooltip title="Choose whether to analyze actual metric values or period-to-period changes">
                        <LemonSelect
                            className="w-32"
                            data-attr="alertForm-value-type"
                            value={value || ValueType.RAW}
                            onChange={onChange}
                            options={[
                                {
                                    label: 'Metric',
                                    value: ValueType.RAW,
                                    tooltip: 'Analyze the actual metric values (e.g., 100 users, 500 pageviews)',
                                },
                                {
                                    label: 'Delta',
                                    value: ValueType.DELTA,
                                    tooltip: 'Analyze changes between time periods (e.g., +50 users from yesterday)',
                                },
                            ]}
                        />
                    </Tooltip>
                </LemonField>
            </Group>
        </div>
    )
}
