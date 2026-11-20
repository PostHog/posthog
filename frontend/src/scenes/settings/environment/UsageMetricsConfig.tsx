import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconEllipsis, IconPlus, IconPlusSmall } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonMenu,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Text,
} from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TeamMembershipLevel } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import type { GroupUsageMetricApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { QuillUsageMetricsForm } from './QuillUsageMetricsForm'
import { QuillUsageMetricsTable } from './QuillUsageMetricsTable'
import { UsageMetricFiltersEditor } from './UsageMetricFiltersEditor'
import { usageMetricCalculationLabel, usageMetricDisplayLabel, usageMetricSourceLabel } from './usageMetricLabels'
import { UsageMetricEventFilters, getMetricSource, usageMetricsConfigLogic } from './usageMetricsConfigLogic'

function UsageMetricsTable(): JSX.Element {
    const { usageMetrics, usageMetricsLoading } = useValues(usageMetricsConfigLogic)
    const { removeUsageMetric, openModal, setUsageMetricValues } = useActions(usageMetricsConfigLogic)
    const { reportUsageMetricsUpdateButtonClicked } = useActions(eventUsageLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useQuillSurface()

    const handleEdit = (metric: GroupUsageMetricApi): void => {
        openModal()
        setUsageMetricValues({
            ...metric,
            filters: (metric.filters ?? {}) as UsageMetricEventFilters,
        })
        reportUsageMetricsUpdateButtonClicked()
    }

    const handleDelete = (metric: GroupUsageMetricApi): void => {
        LemonDialog.open({
            title: 'Delete usage metric',
            description: `Are you sure you want to delete "${metric.name}"? This action cannot be undone.`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => {
                    removeUsageMetric(metric.id)
                },
                disabledReason: restrictedReason,
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    if (todayRailNav) {
        return (
            <QuillUsageMetricsTable
                metrics={usageMetrics}
                loading={usageMetricsLoading}
                restrictedReason={restrictedReason}
                onEdit={handleEdit}
                onDelete={handleDelete}
            />
        )
    }

    const columns: LemonTableColumns<GroupUsageMetricApi> = [
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
            render: function Render(_, metric) {
                return usageMetricDisplayLabel(metric)
            },
        },
        {
            title: 'Source',
            key: 'source',
            render: function Render(_, metric) {
                return usageMetricSourceLabel(metric)
            },
        },
        {
            title: 'Calculation',
            key: 'math',
            render: function Render(_, metric) {
                return usageMetricCalculationLabel(metric)
            },
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
                                onClick: () => handleEdit(metric),
                                disabledReason: restrictedReason,
                            },
                            {
                                label: 'Delete',
                                status: 'danger',
                                onClick: () => handleDelete(metric),
                                disabledReason: restrictedReason,
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
    const { usageMetric } = useValues(usageMetricsConfigLogic)
    const { setUsageMetricValue } = useActions(usageMetricsConfigLogic)
    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventMetadata,
        TaxonomicFilterGroupType.HogQLExpression,
    ]
    const source = getMetricSource(usageMetric.filters)
    const todayRailNav = useQuillSurface()

    const handleMathChange = (newValue: string, onChange: (value: string) => void): void => {
        onChange(newValue)
        if (newValue === 'count') {
            setUsageMetricValue('math_property', null)
        }
    }

    if (todayRailNav) {
        return (
            <QuillUsageMetricsForm
                source={source}
                taxonomicGroupTypes={taxonomicGroupTypes}
                onMathChange={handleMathChange}
            />
        )
    }

    return (
        <Form id="usageMetric" logic={usageMetricsConfigLogic} formKey="usageMetric" enableFormOnSubmit>
            <div className="flex flex-col gap-2">
                <div className="grid grid-cols-2 gap-2">
                    <LemonField name="name" label="Name">
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

                    <LemonField name="math" label="Calculation">
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                options={[
                                    {
                                        value: 'count',
                                        label: source === 'data_warehouse' ? 'Count of rows' : 'Count of events',
                                    },
                                    {
                                        value: 'sum',
                                        label: source === 'data_warehouse' ? 'Sum of column' : 'Sum of property',
                                    },
                                ]}
                                onChange={(newValue) => handleMathChange(newValue, onChange)}
                            />
                        )}
                    </LemonField>

                    {usageMetric.math === 'sum' && (
                        <LemonField
                            name="math_property"
                            label={source === 'data_warehouse' ? 'Column to sum' : 'Property to sum'}
                        >
                            {({ value, onChange }) =>
                                source === 'data_warehouse' ? (
                                    <LemonInput
                                        value={value ?? ''}
                                        onChange={(newValue) => onChange(newValue || null)}
                                        placeholder="amount"
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
                        </LemonField>
                    )}
                </div>

                <div className="grid grid-cols-1 gap-2">
                    <LemonField
                        name="filters"
                        label="Match events or data warehouse table"
                        help={
                            source === 'data_warehouse'
                                ? 'Data warehouse metrics are limited to a single table and currently only render on group profiles.'
                                : 'Pick events to match, or switch to a data warehouse table. Only one source can be active per metric.'
                        }
                    >
                        {({ value, onChange }) => (
                            <UsageMetricFiltersEditor
                                value={value}
                                onChange={onChange}
                                source={source}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                            />
                        )}
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
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const todayRailNav = useQuillSurface()

    useOnMountEffect(() => {
        reportUsageMetricsSettingsViewed()
    })

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    Define what usage means for your product based on one or more events.
                    <br />
                    Usage metrics are displayed in the person {groupsEnabled ? 'and group profiles' : 'profile'}.
                </Text>
                <Button variant="primary" onClick={openModal} disabledReason={restrictedReason}>
                    <IconPlus />
                    Add metric
                </Button>
                <UsageMetricsTable />
                <UsageMetricsModal />
            </div>
        )
    }

    return (
        <>
            <p>
                Define what usage means for your product based on one or more events.
                <br />
                Usage metrics are displayed in the person {groupsEnabled ? 'and group profiles' : 'profile'}.
            </p>
            <div className="flex flex-col gap-2 items-start">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={openModal}
                    icon={<IconPlusSmall />}
                    disabledReason={restrictedReason}
                >
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
    const todayRailNav = useQuillSurface()

    if (todayRailNav) {
        return (
            <Dialog
                open={isModalOpen}
                onOpenChange={(open: boolean) => {
                    if (!open) {
                        closeModal()
                    }
                }}
            >
                <DialogContent className="sm:max-w-160">
                    <DialogHeader>
                        <DialogTitle>Add usage metric</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <UsageMetricsForm />
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={closeModal} data-attr="cancel-create-usage-metric">
                            Cancel
                        </Button>
                        <Button type="submit" form="usageMetric" variant="primary" data-attr="create-usage-metric">
                            Save
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        )
    }

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
