import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconEllipsis, IconPlusSmall } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonMenu,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { AnyPropertyFilter, EntityTypes, FilterType } from '~/types'

import { UsageMetric, usageMetricsConfigLogic } from './usageMetricsConfigLogic'

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

function UsageMetricsTable(): JSX.Element {
    const { usageMetrics, usageMetricsLoading } = useValues(usageMetricsConfigLogic)
    const { removeUsageMetric, openModal, setUsageMetricValues } = useActions(usageMetricsConfigLogic)
    const { reportUsageMetricsUpdateButtonClicked } = useActions(eventUsageLogic)

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
                                    openModal()
                                    setUsageMetricValues(metric)
                                    reportUsageMetricsUpdateButtonClicked()
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
                                            onClick: () => {
                                                removeUsageMetric(metric.id)
                                            },
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

function UsageMetricsForm(): JSX.Element {
    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.EventMetadata,
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    return (
        <Form id="usageMetric" logic={usageMetricsConfigLogic} formKey="usageMetric" enableFormOnSubmit>
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

                    {/*Commenting this out as sparkline display is not supported yet*/}
                    {/*<LemonField name="display" label="Display">
                        <LemonSelect
                            options={[
                                { value: 'number', label: 'Number' },
                                { value: 'sparkline', label: 'Sparkline' },
                            ]}
                        />
                    </LemonField>*/}
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
                                        pageKey="UsageMetricsConfig"
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
            </div>
        </Form>
    )
}

export function UsageMetricsConfig(): JSX.Element {
    const { openModal } = useActions(usageMetricsConfigLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const { reportUsageMetricsSettingsViewed } = useActions(eventUsageLogic)

    useOnMountEffect(() => {
        reportUsageMetricsSettingsViewed()
    })

    return (
        <>
            <p>
                Define what usage means for your product based on one or more events.
                <br />
                Usage metrics are displayed in the person {groupsEnabled ? 'and group profiles' : 'profile'}.
            </p>
            <div className="flex flex-col gap-2 items-start">
                <LemonButton type="primary" size="small" onClick={openModal} icon={<IconPlusSmall />}>
                    Add metric
                </LemonButton>
                <UsageMetricsTable />
                <UsageMetricsModal />
            </div>
        </>
    )
}

export function UsageMetricsModal(): JSX.Element {
    const { isModalOpen } = useValues(usageMetricsConfigLogic)
    const { closeModal } = useActions(usageMetricsConfigLogic)

    return (
        <LemonModal
            title="Add usage metric"
            isOpen={isModalOpen}
            onClose={closeModal}
            children={<UsageMetricsForm />}
            footer={
                <>
                    <LemonButton
                        htmlType="submit"
                        form="usageMetric"
                        type="primary"
                        children="Save"
                        data-attr="create-usage-metric"
                    />
                    <LemonButton children="Cancel" onClick={closeModal} data-attr="cancel-create-usage-metric" />
                </>
            }
        />
    )
}
