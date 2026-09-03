import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import {
    ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY,
    AccountDetailView,
    canEditAccountDetailView,
    deserializeAccountDetailView,
    resolvePinnedViews,
    serializeAccountDetailView,
} from './accountDetailViews'

function buildRow(overrides: Partial<ColumnConfigurationApi> = {}): ColumnConfigurationApi {
    return {
        id: 'row-1',
        context_key: ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY,
        name: 'Renewal watch',
        columns: ['summary', 'usage'],
        visibility: 'shared',
        properties: {},
        created_by: 7,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }
}

function buildView(id: string, overrides: Partial<AccountDetailView> = {}): AccountDetailView {
    return {
        id,
        name: id,
        scope: 'team',
        widgets: ['summary'],
        text: '',
        createdBy: 7,
        isBuiltIn: false,
        ...overrides,
    }
}

describe('accountDetailViews', () => {
    it('round-trips a view through the column configuration payload', () => {
        const view = deserializeAccountDetailView(
            buildRow({ visibility: 'private', properties: { text: 'Renewal is close.' } })
        )

        expect(view).toEqual({
            id: 'row-1',
            name: 'Renewal watch',
            scope: 'personal',
            widgets: ['summary', 'usage'],
            text: 'Renewal is close.',
            createdBy: 7,
            isBuiltIn: false,
        })
        expect(serializeAccountDetailView(view)).toEqual({
            context_key: ACCOUNT_DETAIL_VIEWS_CONTEXT_KEY,
            name: 'Renewal watch',
            columns: ['summary', 'usage'],
            visibility: 'private',
            properties: { text: 'Renewal is close.' },
        })
    })

    it('drops widget kinds and properties it does not know', () => {
        const view = deserializeAccountDetailView(
            buildRow({ columns: ['summary', 'billing_chart', 'related_people'], properties: { text: 42 } })
        )

        expect(view.widgets).toEqual(['summary', 'related_people'])
        expect(view.text).toBe('')
    })

    it.each([
        ['no stored pins', null, ['a', 'b', 'c', 'd', 'e']],
        ['stored order with a stale id', ['c', 'gone', 'a'], ['c', 'a']],
        ['more pins than slots', ['f', 'e', 'd', 'c', 'b', 'a'], ['f', 'e', 'd', 'c', 'b']],
        ['duplicate ids', ['a', 'a', 'b'], ['a', 'b']],
    ])('resolves pinned views with %s', (_label, pinnedIds, expectedIds) => {
        const views = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => buildView(id))

        expect(resolvePinnedViews(views, pinnedIds).map((view) => view.id)).toEqual(expectedIds)
    })

    it.each([
        ['the built-in view', buildView('overview', { isBuiltIn: true, createdBy: null }), 3, true],
        ['a view the person created', buildView('mine', { createdBy: 3 }), 3, true],
        ['a view someone else created', buildView('theirs', { createdBy: 9 }), 3, false],
        ['an anonymous viewer', buildView('mine', { createdBy: 3 }), null, false],
    ])('allows editing %s: %s', (_label, view, userId, expected) => {
        expect(canEditAccountDetailView(view, userId)).toBe(expected)
    })
})
