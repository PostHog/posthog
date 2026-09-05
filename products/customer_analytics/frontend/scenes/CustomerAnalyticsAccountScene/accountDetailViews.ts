import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

// pinned: ColumnConfiguration context_key — renaming orphans every saved detail view
export const ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY = 'customer_analytics_account_detail_views'

export const MAX_PINNED_VIEWS = 5

// pinned: URL path segment for the built-in view — bookmarks and docs link to it
export const BUILT_IN_VIEW_ID = 'overview'

export const ACCOUNT_DETAIL_WIDGET_KINDS = ['text', 'summary', 'usage', 'support_tickets', 'related_people'] as const
export type AccountDetailWidgetKind = (typeof ACCOUNT_DETAIL_WIDGET_KINDS)[number]

export const ACCOUNT_DETAIL_WIDGET_LABELS: Record<AccountDetailWidgetKind, string> = {
    text: 'Text',
    summary: 'Account summary',
    usage: 'Usage metrics',
    support_tickets: 'Support tickets',
    related_people: 'Related people',
}

export type AccountDetailViewScope = 'personal' | 'team'

export interface AccountDetailView {
    id: string
    name: string
    scope: AccountDetailViewScope
    widgets: AccountDetailWidgetKind[]
    text: string
    createdBy: number | null
    isBuiltIn: boolean
}

interface AccountDetailViewProperties {
    text?: string
}

// The built-in view is what a team sees before anyone saves a view. It is never
// persisted: the first edit to it creates a personal row and the built-in row goes away.
export const BUILT_IN_VIEW: AccountDetailView = {
    id: BUILT_IN_VIEW_ID,
    name: 'Overview',
    scope: 'personal',
    widgets: ['summary', 'usage', 'related_people', 'support_tickets'],
    text: '',
    createdBy: null,
    isBuiltIn: true,
}

export function isAccountDetailWidgetKind(value: unknown): value is AccountDetailWidgetKind {
    return typeof value === 'string' && (ACCOUNT_DETAIL_WIDGET_KINDS as readonly string[]).includes(value)
}

function readProperties(properties: unknown): AccountDetailViewProperties {
    if (!properties || typeof properties !== 'object') {
        return {}
    }
    const text = (properties as Record<string, unknown>).text
    return { text: typeof text === 'string' ? text : undefined }
}

export function deserializeAccountDetailView(row: ColumnConfigurationApi): AccountDetailView {
    return {
        id: row.id,
        name: row.name ?? 'View',
        scope: row.visibility === 'private' ? 'personal' : 'team',
        widgets: (row.columns ?? []).filter(isAccountDetailWidgetKind),
        text: readProperties(row.properties).text ?? '',
        createdBy: row.created_by,
        isBuiltIn: false,
    }
}

// `columns` carries the ordered widget kinds because the API requires a non-empty list
// there; a view with no widgets cannot be saved, which matches the empty-canvas rule.
export function serializeAccountDetailView(
    view: Pick<AccountDetailView, 'name' | 'scope' | 'widgets' | 'text'>
): Pick<ColumnConfigurationApi, 'context_key' | 'name' | 'columns' | 'visibility' | 'properties'> {
    return {
        context_key: ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY,
        name: view.name,
        columns: view.widgets,
        visibility: view.scope === 'personal' ? 'private' : 'shared',
        properties: view.text ? { text: view.text } : {},
    }
}

// Pins are a per-person ordering over the views a person can see. Ids that no longer
// resolve (a deleted view, another person's private view) drop out; a person with no
// stored pins gets the first views the list returns.
export function resolvePinnedViews(views: AccountDetailView[], pinnedIds: string[] | null): AccountDetailView[] {
    if (pinnedIds === null) {
        return views.slice(0, MAX_PINNED_VIEWS)
    }
    const byId = new Map(views.map((view) => [view.id, view]))
    const pinned: AccountDetailView[] = []
    for (const id of pinnedIds) {
        const view = byId.get(id)
        if (view && !pinned.includes(view)) {
            pinned.push(view)
        }
    }
    return pinned.slice(0, MAX_PINNED_VIEWS)
}

export function canEditAccountDetailView(view: AccountDetailView, currentUserId: number | null): boolean {
    return view.isBuiltIn || (currentUserId !== null && view.createdBy === currentUserId)
}
