import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { getGoalFilterSummary, getGoalTypeLabel } from 'lib/components/CoreEvents'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { uuid } from 'lib/utils'
import { ActionFilter as ActionFilterComponent } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import {
    ActionsNode,
    ConversionGoalFilter,
    CoreEvent,
    CoreEventCategory,
    DataWarehouseNode,
    EventsNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ActionFilter, BaseMathType, DataWarehouseFilter, FilterType, GroupMathType, PropertyMathType } from '~/types'

import { coreEventsLogic } from './coreEventsLogic'

// Only allow: total count, unique users/groups, and property sum
const ALLOWED_MATH_TYPES = [
    BaseMathType.TotalCount,
    BaseMathType.UniqueUsers,
    GroupMathType.UniqueGroup,
    PropertyMathType.Sum,
] as const

const CATEGORY_OPTIONS = [
    { value: CoreEventCategory.Acquisition, label: 'Acquisition', description: 'Sign up, app install' },
    { value: CoreEventCategory.Activation, label: 'Activation', description: 'Onboarding, first core action' },
    {
        value: CoreEventCategory.Monetization,
        label: 'Monetization',
        description: 'Purchase, subscription started',
    },
    { value: CoreEventCategory.Expansion, label: 'Expansion', description: 'Plan upgraded' },
    { value: CoreEventCategory.Referral, label: 'Referral', description: 'Invite sent' },
    { value: CoreEventCategory.Retention, label: 'Retention', description: 'Repeat purchase' },
    { value: CoreEventCategory.Churn, label: 'Churn', description: 'Subscription canceled' },
    { value: CoreEventCategory.Reactivation, label: 'Reactivation', description: 'Returned after churn' },
]

// Convert ActionFilter format to our filter node format
function actionFilterToNode(filters: FilterType): EventsNode | ActionsNode | DataWarehouseNode | null {
    const series = actionsAndEventsToSeries(
        {
            actions: filters.actions as ActionFilter[] | undefined,
            events: filters.events as ActionFilter[] | undefined,
            data_warehouse: filters.data_warehouse as DataWarehouseFilter[] | undefined,
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
    event: 'Please select an event, action, or data warehouse table',
}

interface FormState {
    id: string | null // null for new, string for editing
    name: string
    description: string
    category: CoreEventCategory | null
    filter: EventsNode | ActionsNode | DataWarehouseNode
}

const createEmptyFormState = (): FormState => ({
    id: null,
    name: '',
    description: '',
    category: null,
    filter: defaultFilter,
})

const eventToFormState = (event: CoreEvent): FormState => ({
    id: event.id,
    name: event.name,
    description: event.description || '',
    category: event.category,
    filter: event.filter,
})

/** Convert legacy ConversionGoalFilter to FormState for migration */
function legacyGoalToFormState(goal: ConversionGoalFilter): FormState {
    // Extract the filter part (without conversion_goal_id, conversion_goal_name, schema_map)
    const { conversion_goal_id, conversion_goal_name, schema_map, ...filterPart } = goal
    return {
        id: null, // New core event
        name: conversion_goal_name || '',
        description: '',
        category: null, // User must select
        filter: filterPart as EventsNode | ActionsNode | DataWarehouseNode,
    }
}

export function CoreEventsSettings(): JSX.Element {
    const { coreEvents } = useValues(coreEventsLogic)
    const { addCoreEvent, updateCoreEvent, removeCoreEvent } = useActions(coreEventsLogic)
    const { conversion_goals: legacyConversionGoals } = useValues(marketingAnalyticsSettingsLogic)
    const { removeConversionGoal } = useActions(marketingAnalyticsSettingsLogic)

    const [isModalOpen, setIsModalOpen] = useState(false)
    const [formState, setFormState] = useState<FormState>(createEmptyFormState())
    const [migratingGoal, setMigratingGoal] = useState<ConversionGoalFilter | null>(null)

    const isEditing = formState.id !== null

    const handleOpenNewModal = (): void => {
        setFormState(createEmptyFormState())
        setIsModalOpen(true)
    }

    const handleOpenEditModal = (event: CoreEvent): void => {
        setFormState(eventToFormState(event))
        setMigratingGoal(null)
        setIsModalOpen(true)
    }

    const handleMigrateLegacyGoal = (goal: ConversionGoalFilter): void => {
        setFormState(legacyGoalToFormState(goal))
        setMigratingGoal(goal)
        setIsModalOpen(true)
    }

    const handleCloseModal = (): void => {
        setIsModalOpen(false)
        setFormState(createEmptyFormState())
        setMigratingGoal(null)
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
        if (!formState.name.trim() || !formState.category) {
            return
        }

        const event: CoreEvent = {
            id: formState.id || uuid(),
            name: formState.name.trim(),
            description: formState.description.trim() || undefined,
            category: formState.category,
            filter: formState.filter,
        }

        if (isEditing) {
            updateCoreEvent(event)
        } else {
            addCoreEvent(event)
        }

        // If migrating, also remove the legacy conversion goal
        if (migratingGoal) {
            removeConversionGoal(migratingGoal.conversion_goal_id)
        }

        handleCloseModal()
    }

    const getDisabledReason = (): string | undefined => {
        if (!formState.name.trim()) {
            return 'Please enter a name for this core event'
        }
        const hasValidFilter =
            (formState.filter.kind === NodeKind.EventsNode &&
                formState.filter.event != defaultFilter.event &&
                formState.filter.kind === NodeKind.EventsNode &&
                formState.filter.event) ||
            (formState.filter.kind === NodeKind.ActionsNode && formState.filter.id !== undefined) ||
            (formState.filter.kind === NodeKind.DataWarehouseNode && formState.filter.table_name)

        if (!hasValidFilter) {
            return 'Please select an event, action, or data warehouse table'
        }
        if (!formState.category) {
            return 'Please select a category'
        }
        return undefined
    }

    const disabledReason = getDisabledReason()

    // Build filter for ActionFilterComponent
    const currentFilter = nodeToActionFilter(formState.filter)

    const hasLegacyGoals = legacyConversionGoals.length > 0
    const isMigrating = migratingGoal !== null

    return (
        <div className="space-y-4">
            <p className="text-muted">
                Core events are reusable event definitions. Define your key business events once — like signups,
                purchases, or subscriptions — and use them consistently across your analytics.
            </p>

            {hasLegacyGoals && (
                <LemonBanner type="warning" className="mb-2">
                    <div>
                        <strong>Migrate your Marketing conversion goals</strong>
                        <p className="text-sm mt-1">
                            You have {legacyConversionGoals.length} legacy conversion goal
                            {legacyConversionGoals.length === 1 ? '' : 's'} in Marketing analytics. Migrate them to Core
                            Events to manage them centrally.
                        </p>
                    </div>
                </LemonBanner>
            )}

            {hasLegacyGoals && (
                <div className="border border-warning rounded p-4 space-y-3 bg-warning-highlight">
                    <h4 className="font-medium text-warning-dark">Legacy Marketing conversion goals</h4>
                    <p className="text-sm text-muted">
                        These goals are only available in Marketing analytics. Migrate them to Core Events to share them
                        across products.
                    </p>
                    <LemonTable
                        rowKey={(item) => item.conversion_goal_id}
                        dataSource={legacyConversionGoals}
                        size="small"
                        columns={[
                            {
                                key: 'name',
                                title: 'Name',
                                render: (_, goal: ConversionGoalFilter) => (
                                    <span className="font-medium">{goal.conversion_goal_name}</span>
                                ),
                            },
                            {
                                key: 'type',
                                title: 'Type',
                                render: (_, goal: ConversionGoalFilter) => {
                                    if (goal.kind === NodeKind.EventsNode) {
                                        return 'Event'
                                    }
                                    if (goal.kind === NodeKind.ActionsNode) {
                                        return 'Action'
                                    }
                                    if (goal.kind === NodeKind.DataWarehouseNode) {
                                        return 'Data warehouse'
                                    }
                                    return 'Unknown'
                                },
                            },
                            {
                                key: 'actions',
                                title: '',
                                width: 140,
                                render: (_, goal: ConversionGoalFilter) => (
                                    <div className="flex gap-1">
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => handleMigrateLegacyGoal(goal)}
                                        >
                                            Migrate
                                        </LemonButton>
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            status="danger"
                                            onClick={() => removeConversionGoal(goal.conversion_goal_id)}
                                            tooltip="Delete without migrating"
                                        />
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
            )}

            <div className="flex justify-between items-center">
                <h3 className="font-bold">
                    {coreEvents.length === 0
                        ? 'No core events configured'
                        : `${coreEvents.length} core event${coreEvents.length === 1 ? '' : 's'}`}
                </h3>
                <LemonButton type="primary" icon={<IconPlusSmall />} onClick={handleOpenNewModal}>
                    Add core event
                </LemonButton>
            </div>

            <LemonTable
                rowKey={(item) => item.id}
                dataSource={coreEvents}
                columns={[
                    {
                        key: 'name',
                        title: 'Name',
                        render: (_, event: CoreEvent) => <span className="font-medium">{event.name}</span>,
                    },
                    {
                        key: 'type',
                        title: 'Type',
                        render: (_, event: CoreEvent) => getGoalTypeLabel(event),
                    },
                    {
                        key: 'filter',
                        title: 'Filter',
                        render: (_, event: CoreEvent) => (
                            <span className="text-muted">{getGoalFilterSummary(event)}</span>
                        ),
                    },
                    {
                        key: 'category',
                        title: 'Category',
                        render: (_, event: CoreEvent) =>
                            event.category
                                ? CATEGORY_OPTIONS.find((o) => o.value === event.category)?.label || event.category
                                : '-',
                    },
                    {
                        key: 'actions',
                        title: 'Actions',
                        width: 100,
                        render: (_, event: CoreEvent) => (
                            <div className="flex gap-1">
                                <LemonButton
                                    icon={<IconPencil />}
                                    size="small"
                                    onClick={() => handleOpenEditModal(event)}
                                    tooltip="Edit"
                                />
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    status="danger"
                                    onClick={() => removeCoreEvent(event.id)}
                                    tooltip="Remove"
                                />
                            </div>
                        ),
                    },
                ]}
                emptyState="No core events configured yet. Add your first core event above."
            />

            <LemonModal
                isOpen={isModalOpen}
                onClose={handleCloseModal}
                title={
                    isMigrating
                        ? `Migrate "${migratingGoal?.conversion_goal_name}" to Core Event`
                        : isEditing
                          ? 'Edit core event'
                          : 'Add core event'
                }
                width="40rem"
                footer={
                    <>
                        <LemonButton onClick={handleCloseModal}>Cancel</LemonButton>
                        <LemonButton type="primary" onClick={handleSave} disabledReason={disabledReason}>
                            {isMigrating ? 'Migrate to Core Event' : isEditing ? 'Update' : 'Add'}
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-4">
                    {isMigrating && (
                        <LemonBanner type="warning">
                            <p className="text-sm">
                                This will create a new Core Event and remove the legacy Marketing conversion goal.
                            </p>
                        </LemonBanner>
                    )}

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
                            placeholder="Describe what this core event tracks"
                        />
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>Event, action, or data warehouse table</LemonLabel>
                        <ActionFilterComponent
                            bordered
                            filters={currentFilter}
                            setFilters={handleFilterChange}
                            typeKey="core-events-settings"
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
                            excludedProperties={{
                                [TaxonomicFilterGroupType.Events]: [null],
                            }}
                        />
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>Category</LemonLabel>
                        <LemonSelect
                            value={formState.category}
                            onChange={(value) => setFormState((prev) => ({ ...prev, category: value }))}
                            options={CATEGORY_OPTIONS}
                            placeholder="Select a category"
                        />
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}
