import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { uuid } from 'lib/utils'
import { ActionFilter as ActionFilterComponent } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import {
    ActionsNode,
    ConversionGoal,
    ConversionGoalCategory,
    DataWarehouseNode,
    EventsNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ActionFilter, BaseMathType, FilterType, GroupMathType, PropertyMathType } from '~/types'

import { conversionGoalsLogic } from './conversionGoalsLogic'

// Only allow: total count, unique users/groups, and property sum
const ALLOWED_MATH_TYPES = [
    BaseMathType.TotalCount,
    BaseMathType.UniqueUsers,
    GroupMathType.UniqueGroup,
    PropertyMathType.Sum,
] as const

const CATEGORY_OPTIONS = [
    { value: ConversionGoalCategory.Acquisition, label: 'Acquisition', description: 'Sign up, app install' },
    { value: ConversionGoalCategory.Activation, label: 'Activation', description: 'Onboarding, first core action' },
    {
        value: ConversionGoalCategory.Monetization,
        label: 'Monetization',
        description: 'Purchase, subscription started',
    },
    { value: ConversionGoalCategory.Expansion, label: 'Expansion', description: 'Plan upgraded' },
    { value: ConversionGoalCategory.Referral, label: 'Referral', description: 'Invite sent' },
    { value: ConversionGoalCategory.Retention, label: 'Retention', description: 'Repeat purchase' },
    { value: ConversionGoalCategory.Churn, label: 'Churn', description: 'Subscription canceled' },
    { value: ConversionGoalCategory.Reactivation, label: 'Reactivation', description: 'Returned after churn' },
]

function getFilterTypeLabel(filter: EventsNode | ActionsNode | DataWarehouseNode): string {
    switch (filter.kind) {
        case NodeKind.EventsNode:
            return 'Event'
        case NodeKind.ActionsNode:
            return 'Action'
        case NodeKind.DataWarehouseNode:
            return 'Data warehouse'
        default:
            return 'Unknown'
    }
}

function getFilterSummary(filter: EventsNode | ActionsNode | DataWarehouseNode): string {
    switch (filter.kind) {
        case NodeKind.EventsNode:
            return filter.event || 'All events'
        case NodeKind.ActionsNode:
            return filter.name || `Action #${filter.id}`
        case NodeKind.DataWarehouseNode:
            return filter.table_name || 'Unknown table'
        default:
            return 'Unknown'
    }
}

// Convert ActionFilter format to our filter node format
function actionFilterToNode(filters: FilterType): EventsNode | ActionsNode | DataWarehouseNode | null {
    const series = actionsAndEventsToSeries(
        {
            actions: filters.actions,
            events: filters.events,
            data_warehouse: filters.data_warehouse,
        },
        true,
        MathAvailability.All
    )

    if (series.length > 0) {
        return series[0] as EventsNode | ActionsNode | DataWarehouseNode
    }
    return null
}

// Convert our filter node to ActionFilter format for the picker
function nodeToActionFilter(filter: EventsNode | ActionsNode | DataWarehouseNode | null): Partial<FilterType> {
    if (!filter) {
        return { events: [], actions: [], data_warehouse: [] }
    }

    switch (filter.kind) {
        case NodeKind.EventsNode:
            return {
                events: [
                    {
                        id: filter.event || null,
                        name: filter.name,
                        type: 'events',
                        math: filter.math || BaseMathType.TotalCount,
                        math_property: filter.math_property,
                        properties: filter.properties,
                    } as ActionFilter,
                ],
                actions: [],
                data_warehouse: [],
            }
        case NodeKind.ActionsNode:
            return {
                events: [],
                actions: [
                    {
                        id: filter.id,
                        name: filter.name,
                        type: 'actions',
                        math: filter.math || BaseMathType.TotalCount,
                        math_property: filter.math_property,
                        properties: filter.properties,
                    } as ActionFilter,
                ],
                data_warehouse: [],
            }
        case NodeKind.DataWarehouseNode:
            return {
                events: [],
                actions: [],
                data_warehouse: [
                    {
                        id: filter.table_name,
                        name: filter.name || filter.table_name,
                        type: 'data_warehouse',
                        math: filter.math || BaseMathType.TotalCount,
                        math_property: filter.math_property,
                        id_field: filter.id_field,
                        timestamp_field: filter.timestamp_field,
                        distinct_id_field: filter.distinct_id_field,
                    } as ActionFilter,
                ],
            }
        default:
            return { events: [], actions: [], data_warehouse: [] }
    }
}

const defaultFilter: EventsNode = {
    kind: NodeKind.EventsNode,
    event: '',
}

interface FormState {
    id: string | null // null for new, string for editing
    name: string
    description: string
    category: ConversionGoalCategory | null
    filter: EventsNode | ActionsNode | DataWarehouseNode
}

const createEmptyFormState = (): FormState => ({
    id: null,
    name: '',
    description: '',
    category: null,
    filter: defaultFilter,
})

const goalToFormState = (goal: ConversionGoal): FormState => ({
    id: goal.id,
    name: goal.name,
    description: goal.description || '',
    category: goal.category || null,
    filter: goal.filter,
})

export function ConversionGoalsSettings(): JSX.Element {
    const { conversionGoals } = useValues(conversionGoalsLogic)
    const { addConversionGoal, updateConversionGoal, removeConversionGoal } = useActions(conversionGoalsLogic)

    const [isModalOpen, setIsModalOpen] = useState(false)
    const [formState, setFormState] = useState<FormState>(createEmptyFormState())

    const isEditing = formState.id !== null

    const handleOpenNewModal = (): void => {
        setFormState(createEmptyFormState())
        setIsModalOpen(true)
    }

    const handleOpenEditModal = (goal: ConversionGoal): void => {
        setFormState(goalToFormState(goal))
        setIsModalOpen(true)
    }

    const handleCloseModal = (): void => {
        setIsModalOpen(false)
        setFormState(createEmptyFormState())
    }

    const handleFilterChange = (filters: Partial<FilterType>): void => {
        const node = actionFilterToNode(filters as FilterType)
        if (node) {
            setFormState((prev) => ({
                ...prev,
                filter: node,
                // Auto-fill name from event/action name if not already set
                name: prev.name || node.name || (node.kind === NodeKind.EventsNode ? node.event : '') || '',
            }))
        }
    }

    const handleSave = (): void => {
        if (!formState.name.trim()) {
            return
        }

        const goal: ConversionGoal = {
            id: formState.id || uuid(),
            name: formState.name.trim(),
            description: formState.description.trim() || undefined,
            category: formState.category || undefined,
            filter: formState.filter,
        }

        if (isEditing) {
            updateConversionGoal(goal)
        } else {
            addConversionGoal(goal)
        }
        handleCloseModal()
    }

    const isFormValid =
        formState.name.trim() !== '' &&
        ((formState.filter.kind === NodeKind.EventsNode && formState.filter.event) ||
            (formState.filter.kind === NodeKind.ActionsNode && formState.filter.id) ||
            (formState.filter.kind === NodeKind.DataWarehouseNode && formState.filter.table_name))

    // Build filter for ActionFilterComponent
    const currentFilter = nodeToActionFilter(formState.filter)

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h3 className="font-bold">
                    {conversionGoals.length === 0
                        ? 'No conversion goals configured'
                        : `${conversionGoals.length} conversion goal${conversionGoals.length === 1 ? '' : 's'}`}
                </h3>
                <LemonButton type="primary" icon={<IconPlusSmall />} onClick={handleOpenNewModal}>
                    Add conversion goal
                </LemonButton>
            </div>

            <LemonTable
                rowKey={(item) => item.id}
                dataSource={conversionGoals}
                columns={[
                    {
                        key: 'name',
                        title: 'Name',
                        render: (_, goal: ConversionGoal) => <span className="font-medium">{goal.name}</span>,
                    },
                    {
                        key: 'type',
                        title: 'Type',
                        render: (_, goal: ConversionGoal) => getFilterTypeLabel(goal.filter),
                    },
                    {
                        key: 'filter',
                        title: 'Filter',
                        render: (_, goal: ConversionGoal) => (
                            <span className="text-muted">{getFilterSummary(goal.filter)}</span>
                        ),
                    },
                    {
                        key: 'category',
                        title: 'Category',
                        render: (_, goal: ConversionGoal) =>
                            goal.category
                                ? CATEGORY_OPTIONS.find((o) => o.value === goal.category)?.label || goal.category
                                : '-',
                    },
                    {
                        key: 'actions',
                        title: 'Actions',
                        width: 100,
                        render: (_, goal: ConversionGoal) => (
                            <div className="flex gap-1">
                                <LemonButton
                                    icon={<IconPencil />}
                                    size="small"
                                    onClick={() => handleOpenEditModal(goal)}
                                    tooltip="Edit"
                                />
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    status="danger"
                                    onClick={() => removeConversionGoal(goal.id)}
                                    tooltip="Remove"
                                />
                            </div>
                        ),
                    },
                ]}
                emptyState="No conversion goals configured yet. Add your first conversion goal above."
            />

            <LemonModal
                isOpen={isModalOpen}
                onClose={handleCloseModal}
                title={isEditing ? 'Edit conversion goal' : 'Add conversion goal'}
                footer={
                    <>
                        <LemonButton onClick={handleCloseModal}>Cancel</LemonButton>
                        <LemonButton type="primary" onClick={handleSave} disabled={!isFormValid}>
                            {isEditing ? 'Update' : 'Add'}
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-4">
                    <div className="space-y-1">
                        <LemonLabel>Name</LemonLabel>
                        <LemonInput
                            value={formState.name}
                            onChange={(value) => setFormState((prev) => ({ ...prev, name: value }))}
                            placeholder="e.g., Purchase, Sign up"
                        />
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>Description (optional)</LemonLabel>
                        <LemonTextArea
                            value={formState.description}
                            onChange={(value) => setFormState((prev) => ({ ...prev, description: value }))}
                            placeholder="Describe what this conversion goal tracks"
                        />
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>Event, action, or data warehouse table</LemonLabel>
                        <ActionFilterComponent
                            bordered
                            filters={currentFilter}
                            setFilters={handleFilterChange}
                            typeKey="conversion-goals-settings"
                            mathAvailability={MathAvailability.All}
                            allowedMathTypes={ALLOWED_MATH_TYPES}
                            hideRename
                            hideDuplicate
                            showSeriesIndicator={false}
                            entitiesLimit={1}
                            actionsTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.Events,
                                TaxonomicFilterGroupType.Actions,
                                TaxonomicFilterGroupType.DataWarehouse,
                            ]}
                        />
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>Category (optional)</LemonLabel>
                        <LemonSelect
                            value={formState.category}
                            onChange={(value) => setFormState((prev) => ({ ...prev, category: value }))}
                            options={CATEGORY_OPTIONS}
                            placeholder="Select a category"
                            allowClear
                        />
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}
