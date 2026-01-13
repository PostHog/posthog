import { IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

import {
    ActionsNode,
    CoreEvent,
    CoreEventCategory,
    DataWarehouseNode,
    EventsNode,
    NodeKind,
} from '~/queries/schema/schema-general'

export const CATEGORY_OPTIONS = [
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

export type CategoryOption = (typeof CATEGORY_OPTIONS)[0]

export function getFilterTypeLabel(filter: EventsNode | ActionsNode | DataWarehouseNode): string {
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

export function getFilterSummary(filter: EventsNode | ActionsNode | DataWarehouseNode): string {
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

export function CoreEventCard({
    event,
    onEdit,
    onRemove,
}: {
    event: CoreEvent
    onEdit: () => void
    onRemove: () => void
}): JSX.Element {
    return (
        <div className="border rounded p-3 flex justify-between items-start gap-2 bg-bg-light">
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <span className="font-medium">{event.name}</span>
                    <LemonTag type="muted" size="small">
                        {getFilterTypeLabel(event.filter)}
                    </LemonTag>
                </div>
                <div className="text-muted text-xs mt-0.5">{getFilterSummary(event.filter)}</div>
                {event.description && <div className="text-secondary text-sm mt-1">{event.description}</div>}
            </div>
            <div className="flex gap-1 shrink-0">
                <LemonButton icon={<IconPencil />} size="small" onClick={onEdit} tooltip="Edit" />
                <LemonButton icon={<IconTrash />} size="small" status="danger" onClick={onRemove} tooltip="Remove" />
            </div>
        </div>
    )
}

export function CategorySection({
    category,
    events,
    onEdit,
    onRemove,
    onAdd,
}: {
    category: CategoryOption
    events: CoreEvent[]
    onEdit: (event: CoreEvent) => void
    onRemove: (eventId: string) => void
    onAdd: () => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex justify-between items-start">
                <div>
                    <h4 className="font-semibold text-sm">{category.label}</h4>
                    <p className="text-muted text-xs">{category.description}</p>
                </div>
                <LemonButton
                    icon={<IconPlusSmall />}
                    size="small"
                    onClick={onAdd}
                    tooltip={`Add ${category.label} event`}
                />
            </div>
            {events.length > 0 ? (
                <div className="space-y-2">
                    {events.map((event) => (
                        <CoreEventCard
                            key={event.id}
                            event={event}
                            onEdit={() => onEdit(event)}
                            onRemove={() => onRemove(event.id)}
                        />
                    ))}
                </div>
            ) : (
                <div className="text-muted text-sm italic">No events in this category</div>
            )}
        </div>
    )
}
