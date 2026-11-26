import {
    ActionsNode,
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
