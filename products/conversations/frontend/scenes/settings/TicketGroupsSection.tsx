import {
    DndContext,
    DragEndEvent,
    KeyboardSensor,
    PointerSensor,
    closestCenter,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import {
    SortableContext,
    arrayMove,
    sortableKeyboardCoordinates,
    useSortable,
    verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlus, IconTrash, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonInputSelect, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

import { tagsModel } from '~/models/tagsModel'

import { channelOptions, priorityMultiselectOptions, statusMultiselectOptions } from '../../types'
import { DEFAULT_TICKET_GROUPS, TicketGroup, TicketGroupFilter } from '../tickets/ticketGroups'
import { supportSettingsLogic } from './supportSettingsLogic'

/** What the property dropdown picks between — 'tags' is the ticket_tags
 *  filter type, 'sql' the sql filter type; the rest are ticket_property keys. */
type FilterProperty =
    | 'tags'
    | 'channel_source'
    | 'status'
    | 'priority'
    | 'email_from'
    | 'sla_due_at'
    | 'sla_state'
    | 'created_at'
    | 'sql'

const PROPERTY_OPTIONS: { value: FilterProperty; label: string }[] = [
    { value: 'tags', label: 'Tags' },
    { value: 'channel_source', label: 'Channel' },
    { value: 'status', label: 'Status' },
    { value: 'priority', label: 'Priority' },
    { value: 'email_from', label: 'Email from' },
    { value: 'sla_due_at', label: 'SLA deadline' },
    { value: 'sla_state', label: 'SLA state' },
    { value: 'created_at', label: 'Created' },
    { value: 'sql', label: 'SQL expression' },
]

const OPERATOR_OPTIONS: Record<FilterProperty, { value: string; label: string }[]> = {
    tags: [{ value: 'any_of', label: 'include any of' }],
    sql: [{ value: 'sql', label: 'is true' }],
    channel_source: [{ value: 'in', label: 'is any of' }],
    status: [{ value: 'in', label: 'is any of' }],
    priority: [{ value: 'in', label: 'is any of' }],
    sla_state: [{ value: 'in', label: 'is any of' }],
    email_from: [{ value: 'icontains', label: 'contains' }],
    sla_due_at: [
        { value: 'is_set', label: 'is set' },
        { value: 'is_not_set', label: 'is not set' },
    ],
    created_at: [
        { value: 'date_before', label: 'before' },
        { value: 'date_after', label: 'after' },
    ],
}

const IN_VALUE_OPTIONS: Record<
    'channel_source' | 'status' | 'priority' | 'sla_state',
    { key: string; label: string }[]
> = {
    channel_source: channelOptions
        .filter((option) => option.value !== 'all')
        .map((option) => ({ key: option.value, label: option.label })),
    status: statusMultiselectOptions,
    priority: priorityMultiselectOptions,
    // Mirrors the tickets list's SLA filter (backend/sla.py owns the definitions).
    sla_state: [
        { key: 'breached', label: 'Breached' },
        { key: 'at-risk', label: 'At risk (due within an hour)' },
        { key: 'on-track', label: 'On track' },
    ],
}

function filterProperty(filter: TicketGroupFilter): FilterProperty {
    if (filter.type === 'ticket_tags') {
        return 'tags'
    }
    if (filter.type === 'sql') {
        return 'sql'
    }
    return filter.key
}

function emptyFilterForProperty(property: FilterProperty): TicketGroupFilter {
    switch (property) {
        case 'tags':
            return { type: 'ticket_tags', operator: 'any_of', value: [] }
        case 'sql':
            return { type: 'sql', expression: '' }
        case 'channel_source':
        case 'status':
        case 'priority':
        case 'sla_state':
            return { type: 'ticket_property', key: property, operator: 'in', value: [] }
        case 'email_from':
            return { type: 'ticket_property', key: 'email_from', operator: 'icontains', value: '' }
        case 'sla_due_at':
            return { type: 'ticket_property', key: 'sla_due_at', operator: 'is_set' }
        case 'created_at':
            return { type: 'ticket_property', key: 'created_at', operator: 'date_before', value: '' }
    }
}

interface FilterRowProps {
    filter: TicketGroupFilter
    onChange: (filter: TicketGroupFilter) => void
    onRemove: () => void
}

function FilterRow({ filter, onChange, onRemove }: FilterRowProps): JSX.Element {
    const { tags: tagsAvailable } = useValues(tagsModel)
    const property = filterProperty(filter)

    const setOperator = (operator: string): void => {
        if (filter.type === 'ticket_property' && filter.key === 'sla_due_at') {
            onChange({ ...filter, operator: operator as 'is_set' | 'is_not_set' })
        } else if (filter.type === 'ticket_property' && filter.key === 'created_at') {
            onChange({ ...filter, operator: operator as 'date_before' | 'date_after' })
        }
        // Every other property has exactly one operator — nothing to change.
    }

    let valueControl: JSX.Element | null = null
    if (filter.type === 'sql') {
        valueControl = (
            <div className="flex flex-col flex-1 min-w-0">
                <LemonTextArea
                    className="font-mono"
                    minRows={2}
                    value={filter.expression}
                    onChange={(expression) => onChange({ ...filter, expression })}
                    placeholder="message_count > 5 AND priority = 'high'"
                    data-attr="ticket-group-sql-expression"
                />
                <span className="text-xxs text-muted">
                    A HogQL boolean expression over this ticket's columns, for example{' '}
                    <code>message_count &gt; 5 AND priority = 'high'</code>. Tags aren't available here — use a Ticket
                    tags filter alongside instead. Validated when you save.
                </span>
            </div>
        )
    } else if (filter.type === 'ticket_tags') {
        valueControl = (
            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                value={filter.value}
                onChange={(value) => onChange({ ...filter, value })}
                options={tagsAvailable.map((tag) => ({ key: tag, label: tag }))}
                placeholder="Ticket tags (exact match)"
                className="flex-1"
                data-attr="ticket-group-tags"
            />
        )
    } else if (filter.operator === 'in') {
        valueControl = (
            <LemonInputSelect
                mode="multiple"
                value={filter.value}
                onChange={(value) => onChange({ ...filter, value })}
                options={IN_VALUE_OPTIONS[filter.key]}
                placeholder="Choose values"
                className="flex-1"
                data-attr="ticket-group-filter-values"
            />
        )
    } else if (filter.operator === 'icontains') {
        valueControl = (
            <LemonInput
                value={filter.value}
                onChange={(value) => onChange({ ...filter, value })}
                placeholder="@bigcorp.com"
                className="flex-1"
            />
        )
    } else if (filter.operator === 'date_before' || filter.operator === 'date_after') {
        valueControl = (
            <div className="flex flex-col flex-1 min-w-0">
                <LemonInput
                    value={filter.value}
                    onChange={(value) => onChange({ ...filter, value })}
                    placeholder="-3d"
                />
                <span className="text-xxs text-muted">
                    Relative like "-3d" or "-12h" (units h/d/w/m/y, optional Start/End suffix, e.g. "-1mStart"), or a
                    date like 2026-07-01
                </span>
            </div>
        )
    }

    return (
        <div className="flex items-start gap-2">
            <LemonSelect
                value={property}
                onChange={(next) => onChange(emptyFilterForProperty(next))}
                options={PROPERTY_OPTIONS}
                className="w-30 shrink-0"
                data-attr="ticket-group-filter-property"
            />
            <LemonSelect
                value={filter.type === 'ticket_tags' ? 'any_of' : filter.type === 'sql' ? 'sql' : filter.operator}
                onChange={setOperator}
                options={OPERATOR_OPTIONS[property]}
                className="shrink-0"
                data-attr="ticket-group-filter-operator"
            />
            {valueControl}
            <LemonButton icon={<IconX />} size="small" tooltip="Remove filter" onClick={onRemove} />
        </div>
    )
}

interface SortableGroupRowProps {
    id: string
    group: TicketGroup
    onPatch: (patch: Partial<TicketGroup>) => void
    onRemove: () => void
}

function SortableGroupRow({ id, group, onPatch, onRemove }: SortableGroupRowProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })

    const patchFilter = (index: number, filter: TicketGroupFilter): void =>
        onPatch({ filters: group.filters.map((f, i) => (i === index ? filter : f)) })
    const removeFilter = (index: number): void => onPatch({ filters: group.filters.filter((_, i) => i !== index) })
    const addFilter = (): void => onPatch({ filters: [...group.filters, emptyFilterForProperty('tags')] })

    return (
        <div
            ref={setNodeRef}
            style={{
                transform: CSS.Transform.toString(transform),
                transition: isDragging ? 'none' : transition,
                opacity: isDragging ? 0.8 : 1,
                zIndex: isDragging ? 1000 : 'auto',
                position: 'relative',
            }}
            className="flex items-start gap-2 border rounded p-2 bg-bg-light"
        >
            <div
                className="flex items-center justify-center cursor-grab active:cursor-grabbing px-1 h-10"
                {...attributes}
                {...listeners}
            >
                <SortableDragIcon className="text-muted-alt" />
            </div>
            <LemonInput
                value={group.label}
                onChange={(label) => onPatch({ label })}
                placeholder="Group label"
                className="w-44 shrink-0"
            />
            <div className="flex flex-col gap-2 flex-1 min-w-0">
                {group.filters.map((filter, index) => (
                    <FilterRow
                        key={index}
                        filter={filter}
                        onChange={(next) => patchFilter(index, next)}
                        onRemove={() => removeFilter(index)}
                    />
                ))}
                {group.filters.length === 0 && (
                    <span className="text-muted text-xs h-10 flex items-center">
                        No filters yet — this group matches no tickets until you add one.
                    </span>
                )}
                <div>
                    <LemonButton size="small" type="secondary" icon={<IconPlus />} onClick={addFilter}>
                        Add filter
                    </LemonButton>
                </div>
            </div>
            <LemonButton icon={<IconTrash />} size="small" tooltip="Remove group" onClick={onRemove} />
        </div>
    )
}

export function TicketGroupsSection(): JSX.Element {
    const { ticketGroupsView, ticketGroupsDraft, ticketGroupsCustomized, ticketGroupsError, currentTeamLoading } =
        useValues(supportSettingsLogic)
    const { setTicketGroupsDraft, saveTicketGroups } = useActions(supportSettingsLogic)

    const groups = ticketGroupsView
    const dirty = ticketGroupsDraft !== null

    // Stable per-row ids for drag-and-drop and React keys, so a row's
    // transient input state travels with the row when the list reorders.
    // Mutations below keep this array position-aligned with `groups`; while
    // pristine it just mirrors the saved groups.
    const [rowIds, setRowIds] = useState<string[]>(() => groups.map((_, index) => `row-${index}`))
    const nextIdRef = useRef(groups.length)
    useEffect(() => {
        if (!dirty) {
            setRowIds(groups.map((_, index) => `row-${index}`))
            nextIdRef.current = groups.length
        }
    }, [dirty, groups])
    const ids = rowIds.length === groups.length ? rowIds : groups.map((_, index) => `row-${index}`)

    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )

    const patchGroup = (index: number, patch: Partial<TicketGroup>): void =>
        setTicketGroupsDraft(groups.map((group, i) => (i === index ? { ...group, ...patch } : group)))
    const removeGroup = (index: number): void => {
        setRowIds(ids.filter((_, i) => i !== index))
        setTicketGroupsDraft(groups.filter((_, i) => i !== index))
    }
    const addGroup = (): void => {
        setRowIds([...ids, `row-new-${nextIdRef.current++}`])
        setTicketGroupsDraft([...groups, { label: '', filters: [] }])
    }
    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (over && active.id !== over.id) {
            const oldIndex = ids.indexOf(String(active.id))
            const newIndex = ids.indexOf(String(over.id))
            if (oldIndex !== -1 && newIndex !== -1) {
                setRowIds(arrayMove(ids, oldIndex, newIndex))
                setTicketGroupsDraft(arrayMove(groups, oldIndex, newIndex))
            }
        }
    }

    return (
        <div className="flex flex-col gap-4 max-w-[900px]">
            <ul className="list-disc pl-4 flex flex-col gap-1">
                <li>
                    When sorting tickets by <strong>Ticket group</strong>, it orders tickets by the groups you define
                    below, then by SLA within each group.
                </li>
                <li>A ticket lands in a group when ALL of that group's filters match it.</li>
                <li>When several groups match a ticket, the highest group in the list wins.</li>
                <li>Tickets matching no group land in the top group, so they won't be missed (for triage.)</li>
                <li>The starter groups are just examples, replace them with your own groups and filters.</li>
            </ul>
            <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={handleDragEnd}
                modifiers={[restrictToVerticalAxis]}
            >
                <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                    <div className="flex flex-col gap-2">
                        {groups.map((group, index) => (
                            <SortableGroupRow
                                key={ids[index]}
                                id={ids[index]}
                                group={group}
                                onPatch={(patch) => patchGroup(index, patch)}
                                onRemove={() => removeGroup(index)}
                            />
                        ))}
                    </div>
                </SortableContext>
            </DndContext>
            {ticketGroupsError && <LemonBanner type="warning">{ticketGroupsError}</LemonBanner>}
            <div className="flex items-center gap-2">
                <LemonButton type="secondary" icon={<IconPlus />} onClick={addGroup}>
                    Add group
                </LemonButton>
                <LemonButton
                    type="primary"
                    loading={dirty && currentTeamLoading}
                    disabledReason={!dirty ? 'No unsaved changes' : (ticketGroupsError ?? undefined)}
                    onClick={() => saveTicketGroups(ticketGroupsDraft)}
                >
                    Save groups
                </LemonButton>
                {dirty && (
                    <LemonButton type="tertiary" onClick={() => setTicketGroupsDraft(null)}>
                        Discard changes
                    </LemonButton>
                )}
                {ticketGroupsCustomized && (
                    <LemonButton
                        type="tertiary"
                        status="danger"
                        onClick={() => setTicketGroupsDraft([...DEFAULT_TICKET_GROUPS])}
                        disabledReason={dirty ? 'Save or discard your changes first' : undefined}
                        tooltip="Replace the groups below with the example starter groups — nothing is erased until you save"
                    >
                        Reset to examples
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
