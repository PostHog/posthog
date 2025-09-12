import { useActions, useValues } from 'kea'
import { Form, capitalizeFirstLetter } from 'kea-forms'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonMenu,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, EntityTypes, FilterType } from '~/types'

import { UsageMetric, crmUsageMetricsConfigLogic } from './crmUsageMetricsConfigLogic'

function sanitizeFilters(filters?: FilterType): FilterType {
    if (!filters) {
        return {}
    }

    const sanitized: FilterType = {}
    if (filters.events) {
        sanitized.events = filters.events.map((f) => ({
            id: f.id,
            type: 'events',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    return sanitized
}

function CRMUsageMetricsTable(): JSX.Element {
    const { usageMetrics, usageMetricsLoading } = useValues(crmUsageMetricsConfigLogic)
    const { removeUsageMetric } = useActions(crmUsageMetricsConfigLogic)

    const columns: LemonTableColumns<UsageMetric> = [
        {
            title: 'Name',
            key: 'name',
            dataIndex: 'name',
        },
        {
            title: 'Format',
            key: 'format',
            dataIndex: 'format',
        },
        {
            title: 'Interval',
            key: 'interval',
            dataIndex: 'interval',
        },
        {
            title: 'Display',
            key: 'display',
            dataIndex: 'display',
        },
        {
            title: '',
            key: 'actions',
            width: 24,
            render: function Render(_, metric) {
                return (
                    <LemonMenu
                        items={[
                            {
                                label: 'Edit',
                                onClick: () => {
                                    LemonDialog.open({
                                        title: 'Edit usage metric',
                                        description: (
                                            <div>
                                                <CRMUsageMetricsForm metric={metric} />
                                            </div>
                                        ),
                                        primaryButton: {
                                            htmlType: 'submit',
                                            children: 'Save',
                                            'data-attr': 'update-crm-usage-metric',
                                            form: 'usageMetric',
                                        },
                                        secondaryButton: {
                                            htmlType: 'button',
                                            children: 'Cancel',
                                            'data-attr': 'cancel-update-crm-usage-metric',
                                        },
                                    })
                                },
                            },
                            {
                                label: 'Delete',
                                status: 'danger',
                                onClick: () => {
                                    LemonDialog.open({
                                        title: 'Delete usage metric',
                                        description: `Are you sure you want to delete "${metric.name}"? This action cannot be undone.`,
                                        primaryButton: {
                                            children: 'Delete',
                                            status: 'danger',
                                            onClick: () => removeUsageMetric(metric.id),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                },
                            },
                        ]}
                    >
                        <LemonButton size="small" icon={<IconEllipsis />} />
                    </LemonMenu>
                )
            },
        },
    ]

    return <LemonTable columns={columns} dataSource={usageMetrics} loading={usageMetricsLoading} />
}

interface CRMUsageMetricsFormProps {
    metric?: UsageMetric
}

function CRMUsageMetricsForm({ metric }: CRMUsageMetricsFormProps): JSX.Element {
    const { resetUsageMetric, setIsEditing, setUsageMetricValues } = useActions(crmUsageMetricsConfigLogic)

    if (metric) {
        setUsageMetricValues(metric)
    }

    const handleCancelForm = (): void => {
        resetUsageMetric()
        setIsEditing(false)
    }

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.EventMetadata,
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    return (
        <Form id="usageMetric" logic={crmUsageMetricsConfigLogic} formKey="usageMetric" enableFormOnSubmit>
            <div className="flex flex-col gap-2">
                <div className="grid grid-cols-2 gap-2">
                    <LemonField name="name" label="Name" help="This will be the title of the column in group list">
                        <LemonInput placeholder="Events" />
                    </LemonField>

                    <LemonField name="interval" label="Interval">
                        <LemonSelect
                            options={[
                                { value: 7, label: '7d' },
                                { value: 30, label: '30d' },
                                { value: 90, label: '90d' },
                            ]}
                        />
                    </LemonField>

                    <LemonField name="format" label="Format">
                        <LemonSelect
                            options={[
                                { value: 'currency', label: 'Currency' },
                                { value: 'numeric', label: 'Numeric' },
                            ]}
                        />
                    </LemonField>

                    <LemonField name="display" label="Display">
                        <LemonSelect
                            options={[
                                { value: 'number', label: 'Number' },
                                { value: 'sparkline', label: 'Sparkline' },
                            ]}
                        />
                    </LemonField>
                </div>

                <div className="grid grid-cols-1 gap-2">
                    <LemonField
                        name="filters"
                        label="Match events"
                        help="The usage metric will take into account events matching any of the above. Filters apply for all match events."
                    >
                        {({ value, onChange }) => {
                            const currentFilters = (value ?? {}) as FilterType
                            return (
                                <>
                                    <ActionFilter
                                        bordered
                                        filters={currentFilters}
                                        setFilters={(payload) => {
                                            onChange({
                                                ...currentFilters,
                                                ...sanitizeFilters(payload),
                                            })
                                        }}
                                        typeKey="plugin-filters"
                                        mathAvailability={MathAvailability.None}
                                        hideRename
                                        hideDuplicate
                                        showNestedArrow={false}
                                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                                        propertiesTaxonomicGroupTypes={taxonomicGroupTypes}
                                        propertyFiltersPopover
                                        addFilterDefaultOptions={{
                                            id: '$pageview',
                                            name: '$pageview',
                                            type: EntityTypes.EVENTS,
                                        }}
                                        buttonCopy="Add event matcher"
                                    />
                                    <div className="flex gap-2 justify-between w-full">
                                        <LemonLabel>Filters</LemonLabel>
                                    </div>
                                    <PropertyFilters
                                        propertyFilters={(currentFilters?.properties ?? []) as AnyPropertyFilter[]}
                                        taxonomicGroupTypes={taxonomicGroupTypes}
                                        onChange={(properties: AnyPropertyFilter[]) => {
                                            const newValue = {
                                                ...currentFilters,
                                                properties,
                                            }
                                            onChange(newValue)
                                        }}
                                        pageKey="CRMUsageMetricsConfig"
                                    />
                                    <TestAccountFilterSwitch
                                        checked={currentFilters?.filter_test_accounts ?? false}
                                        onChange={(filter_test_accounts) => {
                                            const newValue = { ...currentFilters, filter_test_accounts }
                                            onChange(newValue)
                                        }}
                                        fullWidth
                                    />
                                </>
                            )
                        }}
                    </LemonField>
                </div>
                <div>
                    {!metric && (
                        <div className="flex gap-2 mt-2">
                            <LemonButton
                                type="primary"
                                data-attr="save-crm-usage-metric"
                                htmlType="submit"
                                form="usageMetric"
                            >
                                Save
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                data-attr="cancel-crm-usage-metric"
                                onClick={handleCancelForm}
                            >
                                Cancel
                            </LemonButton>
                        </div>
                    )}
                </div>
            </div>
        </Form>
    )
}

export function CRMUsageMetricsConfig(): JSX.Element {
    const { isEditing, currentGroupTypeIndex, availableGroupTypes } = useValues(crmUsageMetricsConfigLogic)
    const { setIsEditing, resetUsageMetric, setCurrentGroupTypeIndex } = useActions(crmUsageMetricsConfigLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const handleAddMetric = (): void => {
        resetUsageMetric()
        setIsEditing(true)
    }

    const tabs = availableGroupTypes.map((groupType) => ({
        key: groupType.group_type_index.toString(),
        label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
        content: (
            <div className="flex flex-col gap-2">
                {!isEditing && (
                    <LemonButton onClick={handleAddMetric} icon={<IconPlus />}>
                        Add metric
                    </LemonButton>
                )}
                {isEditing ? <CRMUsageMetricsForm /> : <CRMUsageMetricsTable />}
            </div>
        ),
    }))

    if (availableGroupTypes.length === 0) {
        return <div>No group types available</div>
    }

    return (
        <>
            Choose which events matter for each metric: API calls, feature adoption, session frequency, error rates to
            identify expansion opportunities and churn risk based on real customer behavior.
            <LemonTabs
                activeKey={currentGroupTypeIndex.toString()}
                onChange={(key) => setCurrentGroupTypeIndex(parseInt(key, 10))}
                tabs={tabs}
            />
        </>
    )
}
