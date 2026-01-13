import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { uuid } from 'lib/utils'
import { ActionFilter as ActionFilterComponent } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import {
    ActionsNode,
    CoreEvent,
    CoreEventCategory,
    DataWarehouseNode,
    EventsNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ActionFilter, DataWarehouseFilter, FilterType } from '~/types'

import { CATEGORY_OPTIONS, CategorySection } from './CoreEventComponents'
import { coreEventsLogic } from './coreEventsLogic'

// Convert ActionFilter format to node (strips math and properties for simplified storage)
function actionFilterToNode(filters: FilterType): EventsNode | ActionsNode | DataWarehouseNode | null {
    const event = filters.events?.[0]
    const action = filters.actions?.[0]
    const dataWarehouse = filters.data_warehouse?.[0]

    if (event?.id) {
        return {
            kind: NodeKind.EventsNode,
            event: String(event.id),
            name: event.name,
        } as EventsNode
    }

    if (action?.id !== undefined) {
        return {
            kind: NodeKind.ActionsNode,
            id: Number(action.id),
            name: action.name,
        } as ActionsNode
    }

    if (dataWarehouse?.id) {
        const dw = dataWarehouse as DataWarehouseFilter
        return {
            kind: NodeKind.DataWarehouseNode,
            id: String(dw.id),
            table_name: String(dw.id),
            id_field: dw.id_field || '',
            timestamp_field: dw.timestamp_field || '',
            distinct_id_field: dw.distinct_id_field || '',
            name: dw.name,
        } as DataWarehouseNode
    }

    return null
}

// Convert node to ActionFilter format for the picker
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

export function CoreEventsSettings(): JSX.Element {
    const { coreEvents } = useValues(coreEventsLogic)
    const { addCoreEvent, updateCoreEvent, removeCoreEvent } = useActions(coreEventsLogic)

    const [isModalOpen, setIsModalOpen] = useState(false)
    const [formState, setFormState] = useState<FormState>(createEmptyFormState())
    const [selectedCategory, setSelectedCategory] = useState<CoreEventCategory | null>(null)

    const isEditing = formState.id !== null

    const eventsByCategory = useMemo(() => {
        const grouped: Record<CoreEventCategory, CoreEvent[]> = {} as Record<CoreEventCategory, CoreEvent[]>
        for (const category of CATEGORY_OPTIONS) {
            grouped[category.value] = []
        }
        for (const event of coreEvents) {
            if (event.category && grouped[event.category]) {
                grouped[event.category].push(event)
            }
        }
        return grouped
    }, [coreEvents])

    const categoryCounts = useMemo(() => {
        const counts: Record<CoreEventCategory, number> = {} as Record<CoreEventCategory, number>
        for (const category of CATEGORY_OPTIONS) {
            counts[category.value] = eventsByCategory[category.value].length
        }
        return counts
    }, [eventsByCategory])

    // Filter and sort categories - those with events first, empty ones at the end
    const categoriesToShow = useMemo(() => {
        if (selectedCategory) {
            return CATEGORY_OPTIONS.filter((c) => c.value === selectedCategory)
        }
        return [...CATEGORY_OPTIONS].sort((a, b) => {
            const aCount = eventsByCategory[a.value].length
            const bCount = eventsByCategory[b.value].length
            if (aCount > 0 && bCount === 0) {
                return -1
            }
            if (aCount === 0 && bCount > 0) {
                return 1
            }
            return 0
        })
    }, [selectedCategory, eventsByCategory])

    const handleOpenNewModal = (preselectedCategory?: CoreEventCategory): void => {
        const newState = createEmptyFormState()
        if (preselectedCategory) {
            newState.category = preselectedCategory
        }
        setFormState(newState)
        setIsModalOpen(true)
    }

    const handleOpenEditModal = (event: CoreEvent): void => {
        setFormState(eventToFormState(event))
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

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-start">
                <div>
                    <p className="text-muted">
                        Define the key events that matter for your business across different user lifecycle stages.
                    </p>
                </div>
                <LemonButton type="primary" icon={<IconPlusSmall />} onClick={() => handleOpenNewModal()}>
                    Add core event
                </LemonButton>
            </div>

            {/* Category filter badges */}
            <div className="flex flex-wrap gap-2">
                <LemonTag
                    type={selectedCategory === null ? 'primary' : 'default'}
                    onClick={() => setSelectedCategory(null)}
                    className="cursor-pointer"
                >
                    All ({coreEvents.length})
                </LemonTag>
                {CATEGORY_OPTIONS.map((category) => (
                    <LemonTag
                        key={category.value}
                        type={selectedCategory === category.value ? 'primary' : 'default'}
                        onClick={() => setSelectedCategory(selectedCategory === category.value ? null : category.value)}
                        className="cursor-pointer"
                    >
                        {category.label} ({categoryCounts[category.value]})
                    </LemonTag>
                ))}
            </div>

            {/* Events grouped by category */}
            <div className="space-y-6">
                {categoriesToShow.map((category) => (
                    <CategorySection
                        key={category.value}
                        category={category}
                        events={eventsByCategory[category.value]}
                        onEdit={handleOpenEditModal}
                        onRemove={removeCoreEvent}
                        onAdd={() => handleOpenNewModal(category.value)}
                    />
                ))}
            </div>

            <LemonModal
                isOpen={isModalOpen}
                onClose={handleCloseModal}
                title={isEditing ? 'Edit core event' : 'Add core event'}
                width="40rem"
                footer={
                    <>
                        <LemonButton onClick={handleCloseModal}>Cancel</LemonButton>
                        <LemonButton type="primary" onClick={handleSave} disabledReason={disabledReason}>
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
                            mathAvailability={MathAvailability.None}
                            hideFilter
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

                    <div className="space-y-2">
                        <LemonLabel>Category</LemonLabel>
                        <div className="flex flex-wrap gap-2">
                            {CATEGORY_OPTIONS.map((category) => (
                                <LemonTag
                                    key={category.value}
                                    type={formState.category === category.value ? 'primary' : 'default'}
                                    onClick={() => setFormState((prev) => ({ ...prev, category: category.value }))}
                                    className="cursor-pointer"
                                    title={category.description}
                                >
                                    {category.label}
                                </LemonTag>
                            ))}
                        </div>
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}
