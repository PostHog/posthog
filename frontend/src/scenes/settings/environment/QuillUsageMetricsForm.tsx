import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { FieldDescription, Input } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { QuillOptionSelect } from './QuillOptionSelect'
import { UsageMetricFiltersEditor } from './UsageMetricFiltersEditor'
import { UsageMetricSource, usageMetricsConfigLogic } from './usageMetricsConfigLogic'

const INTERVAL_OPTIONS = [
    { value: 7, label: '7d' },
    { value: 30, label: '30d' },
    { value: 90, label: '90d' },
]

const FORMAT_OPTIONS = [
    { value: 'currency', label: 'Currency' },
    { value: 'numeric', label: 'Numeric' },
]

const DISPLAY_OPTIONS = [
    { value: 'number', label: 'Number' },
    { value: 'sparkline', label: 'Sparkline' },
]

export interface QuillUsageMetricsFormProps {
    source: UsageMetricSource
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    onMathChange: (math: string, onChange: (value: string) => void) => void
}

export function QuillUsageMetricsForm({
    source,
    taxonomicGroupTypes,
    onMathChange,
}: QuillUsageMetricsFormProps): JSX.Element {
    const { usageMetric } = useValues(usageMetricsConfigLogic)

    const mathOptions = [
        { value: 'count', label: source === 'data_warehouse' ? 'Count of rows' : 'Count of events' },
        { value: 'sum', label: source === 'data_warehouse' ? 'Sum of column' : 'Sum of property' },
    ]

    return (
        <Form id="usageMetric" logic={usageMetricsConfigLogic} formKey="usageMetric" enableFormOnSubmit>
            <div className="@container flex flex-col gap-4">
                <div className="grid grid-cols-1 gap-4 @min-[30rem]:grid-cols-2">
                    <QuillSettingFormField name="name" label="Name">
                        {({ id, value, onChange, invalid }) => (
                            <Input
                                id={id}
                                value={value ?? ''}
                                onChange={(event) => onChange(event.target.value)}
                                placeholder="Events"
                                aria-invalid={invalid || undefined}
                            />
                        )}
                    </QuillSettingFormField>

                    <QuillSettingFormField name="interval" label="Interval">
                        {({ id, value, onChange }) => (
                            <QuillOptionSelect id={id} value={value} options={INTERVAL_OPTIONS} onChange={onChange} />
                        )}
                    </QuillSettingFormField>

                    <QuillSettingFormField name="format" label="Format">
                        {({ id, value, onChange }) => (
                            <QuillOptionSelect id={id} value={value} options={FORMAT_OPTIONS} onChange={onChange} />
                        )}
                    </QuillSettingFormField>

                    <QuillSettingFormField name="display" label="Display">
                        {({ id, value, onChange }) => (
                            <QuillOptionSelect id={id} value={value} options={DISPLAY_OPTIONS} onChange={onChange} />
                        )}
                    </QuillSettingFormField>

                    <QuillSettingFormField name="math" label="Calculation">
                        {({ id, value, onChange }) => (
                            <QuillOptionSelect
                                id={id}
                                value={value}
                                options={mathOptions}
                                onChange={(newValue) => onMathChange(newValue, onChange)}
                            />
                        )}
                    </QuillSettingFormField>

                    {usageMetric.math === 'sum' && (
                        <QuillSettingFormField
                            name="math_property"
                            label={source === 'data_warehouse' ? 'Column to sum' : 'Property to sum'}
                        >
                            {({ id, value, onChange, invalid }) =>
                                source === 'data_warehouse' ? (
                                    <Input
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value || null)}
                                        placeholder="amount"
                                        aria-invalid={invalid || undefined}
                                        data-attr="usage-metric-math-property"
                                    />
                                ) : (
                                    <TaxonomicStringPopover
                                        groupType={TaxonomicFilterGroupType.NumericalEventProperties}
                                        value={value}
                                        onChange={onChange}
                                        placeholder="Select property"
                                        data-attr="usage-metric-math-property"
                                        selectingKeyOnly
                                    />
                                )
                            }
                        </QuillSettingFormField>
                    )}
                </div>

                <QuillSettingFormField name="filters" label="Match events or data warehouse table">
                    {({ value, onChange }) => (
                        <div className="flex flex-col gap-2">
                            <FieldDescription>
                                {source === 'data_warehouse'
                                    ? 'Data warehouse metrics are limited to a single table and currently only render on group profiles.'
                                    : 'Pick events to match, or switch to a data warehouse table. Only one source can be active per metric.'}
                            </FieldDescription>
                            <UsageMetricFiltersEditor
                                value={value}
                                onChange={onChange}
                                source={source}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                            />
                        </div>
                    )}
                </QuillSettingFormField>
            </div>
        </Form>
    )
}
