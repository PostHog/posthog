import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { uuid } from 'lib/utils/dom'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { cleanSeriesNodes } from 'scenes/insights/filters/ActionFilter/cleanSeriesNodes'
import { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import {
    ActionsNode,
    CoreEvent,
    CoreEventCategory,
    DataWarehouseNode,
    EventsNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayCategory, GroupMathType, PropertyMathType } from '~/types'

import { CATEGORY_OPTIONS, getFilterSummary, getFilterTypeLabel } from './coreEventLabels'
import { coreEventsLogic } from './coreEventsLogic'
import { QuillCoreEventsSettings } from './QuillCoreEventsSettings'

// Only allow: total count, unique users/groups, and property sum
const ALLOWED_MATH_TYPES = [
    BaseMathType.TotalCount,
    BaseMathType.UniqueUsers,
    GroupMathType.UniqueGroup,
    PropertyMathType.Sum,
] as const

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
    const { coreEvents, coreEventsLoading } = useValues(coreEventsLogic)
    const { addCoreEvent, updateCoreEvent, removeCoreEvent } = useActions(coreEventsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const [isModalOpen, setIsModalOpen] = useState(false)
    const [formState, setFormState] = useState<FormState>(createEmptyFormState)

    const isEditing = formState.id !== null

    const handleOpenNewModal = (): void => {
        setFormState(createEmptyFormState())
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

    const handleSeriesChange = (series: SeriesNode[]): void => {
        // The picker offers events, actions and data warehouse tables only, and cannot combine them.
        const [node] = cleanSeriesNodes(series, MathAvailability.All) as CoreEvent['filter'][]
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

    const filterPicker = (
        <SeriesActionFilter
            bordered
            series={[formState.filter]}
            onChange={handleSeriesChange}
            trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
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
    )

    if (todayRailNav) {
        return (
            <QuillCoreEventsSettings
                coreEvents={coreEvents}
                loading={coreEventsLoading}
                onAdd={handleOpenNewModal}
                onEdit={handleOpenEditModal}
                onRemove={removeCoreEvent}
                dialogOpen={isModalOpen}
                editing={isEditing}
                name={formState.name}
                description={formState.description}
                category={formState.category}
                filterPicker={filterPicker}
                onNameChange={(name) => setFormState((prev) => ({ ...prev, name }))}
                onDescriptionChange={(description) => setFormState((prev) => ({ ...prev, description }))}
                onCategoryChange={(category) => setFormState((prev) => ({ ...prev, category }))}
                onSave={handleSave}
                onClose={handleCloseModal}
                saveDisabledReason={disabledReason}
            />
        )
    }

    return (
        <div className="space-y-4">
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
                        render: (_, event: CoreEvent) => getFilterTypeLabel(event.filter),
                    },
                    {
                        key: 'filter',
                        title: 'Filter',
                        render: (_, event: CoreEvent) => (
                            <span className="text-muted">{getFilterSummary(event.filter)}</span>
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
                        {filterPicker}
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
