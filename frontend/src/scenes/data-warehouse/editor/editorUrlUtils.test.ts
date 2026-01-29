import {
    type EditorTabState,
    type UrlParams,
    getStateIndicators,
    getUrlIndicators,
    needsStateReset,
    shouldOpenFromHashParams,
    shouldSkipUrlAction,
} from './editorUrlUtils'
import type { QueryTab } from './multitabEditorLogic'

const createMockTab = (overrides: Partial<QueryTab> = {}): QueryTab => ({
    uri: { toString: () => 'test://tab' } as any,
    name: 'Test Tab',
    ...overrides,
})

describe('editorUrlUtils', () => {
    describe('getUrlIndicators', () => {
        it.each([
            [
                'extracts from search params',
                { searchParams: { open_view: 'view-1' }, hashParams: {} },
                { view: 'view-1', insight: undefined, draft: undefined, query: undefined },
            ],
            [
                'extracts from hash params',
                { searchParams: {}, hashParams: { insight: 'insight-1' } },
                { view: undefined, insight: 'insight-1', draft: undefined, query: undefined },
            ],
            [
                'prefers search params over hash params',
                { searchParams: { open_view: 'search-view' }, hashParams: { view: 'hash-view' } },
                { view: 'search-view', insight: undefined, draft: undefined, query: undefined },
            ],
            [
                'returns all empty when no params',
                { searchParams: {}, hashParams: {} },
                { view: undefined, insight: undefined, draft: undefined, query: undefined },
            ],
        ])('%s', (_, params, expected) => {
            expect(getUrlIndicators(params as UrlParams)).toEqual(expected)
        })
    })

    describe('getStateIndicators', () => {
        it.each([
            [
                'returns false for all when activeTab is null',
                { queryInput: null, activeTab: null },
                { hasView: false, hasInsight: false, hasDraft: false },
            ],
            [
                'detects view in state',
                { queryInput: 'SELECT 1', activeTab: createMockTab({ view: { id: 'v1' } as any }) },
                { hasView: true, hasInsight: false, hasDraft: false },
            ],
            [
                'detects insight in state',
                { queryInput: 'SELECT 1', activeTab: createMockTab({ insight: { id: 1 } as any }) },
                { hasView: false, hasInsight: true, hasDraft: false },
            ],
            [
                'detects draft in state',
                { queryInput: 'SELECT 1', activeTab: createMockTab({ draft: { id: 'd1' } as any }) },
                { hasView: false, hasInsight: false, hasDraft: true },
            ],
        ])('%s', (_, state, expected) => {
            expect(getStateIndicators(state as EditorTabState)).toEqual(expected)
        })
    })

    describe('needsStateReset', () => {
        it.each([
            [
                'no reset needed when URL and state both empty',
                {},
                { hasView: false, hasInsight: false, hasDraft: false },
                false,
            ],
            [
                'no reset needed when URL has view and state has view',
                { view: 'v1' },
                { hasView: true, hasInsight: false, hasDraft: false },
                false,
            ],
            [
                'reset needed when URL has no view but state has view',
                {},
                { hasView: true, hasInsight: false, hasDraft: false },
                true,
            ],
            [
                'reset needed when URL has no insight but state has insight',
                {},
                { hasView: false, hasInsight: true, hasDraft: false },
                true,
            ],
            [
                'reset needed when URL has no draft but state has draft',
                {},
                { hasView: false, hasInsight: false, hasDraft: true },
                true,
            ],
            [
                'reset needed when switching from view to insight (state has view, URL does not)',
                { insight: 'i1' },
                { hasView: true, hasInsight: false, hasDraft: false },
                true,
            ],
            [
                'reset when URL points to different entity type than state',
                { view: 'v1' },
                { hasView: false, hasInsight: true, hasDraft: false },
                true,
            ],
        ])('%s', (_, urlIndicators, stateIndicators, expected) => {
            const fullUrlIndicators = {
                view: undefined,
                insight: undefined,
                draft: undefined,
                query: undefined,
                ...urlIndicators,
            }
            expect(needsStateReset(fullUrlIndicators, stateIndicators)).toBe(expected)
        })
    })

    describe('shouldSkipUrlAction', () => {
        const emptyParams: UrlParams = { searchParams: {}, hashParams: {} }
        const paramsWithView: UrlParams = { searchParams: { open_view: 'v1' }, hashParams: {} }
        const paramsWithHashQuery: UrlParams = { searchParams: {}, hashParams: { q: 'SELECT 1' } }

        it.each([
            [
                'skip when no params, has query, no reset needed',
                emptyParams,
                { queryInput: 'SELECT 1', activeTab: null },
                false,
                true,
            ],
            [
                'do not skip when no params but queryInput is null',
                emptyParams,
                { queryInput: null, activeTab: null },
                false,
                false,
            ],
            [
                'do not skip when no params, has query, but reset needed',
                emptyParams,
                { queryInput: 'SELECT 1', activeTab: null },
                true,
                false,
            ],
            [
                'do not skip when URL has open_view',
                paramsWithView,
                { queryInput: 'SELECT 1', activeTab: null },
                false,
                false,
            ],
            [
                'do not skip when URL has hash query',
                paramsWithHashQuery,
                { queryInput: 'SELECT 1', activeTab: null },
                false,
                false,
            ],
        ])('%s', (_, params, state, needsReset, expected) => {
            expect(shouldSkipUrlAction(params, state as EditorTabState, needsReset)).toBe(expected)
        })
    })

    describe('shouldOpenFromHashParams', () => {
        it.each([
            ['open when hash value exists and no query loaded', 'view-1', null, false, true],
            ['open when hash value exists and reset needed', 'view-1', 'SELECT 1', true, true],
            ['do not open when hash value exists but query loaded and no reset', 'view-1', 'SELECT 1', false, false],
            ['do not open when hash value is undefined', undefined, null, false, false],
            ['do not open when hash value is empty string', '', null, false, false],
        ])('%s', (_, hashValue, queryInput, needsReset, expected) => {
            expect(shouldOpenFromHashParams(hashValue, queryInput, needsReset)).toBe(expected)
        })
    })
})
