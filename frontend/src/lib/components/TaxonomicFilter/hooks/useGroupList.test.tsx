import { act, cleanup, renderHook, waitFor } from '@testing-library/react'

import api from 'lib/api'

import { PropertyOperator, PropertyFilterType } from '~/types'

import { QuickFilterItem, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
import { NO_ITEM_SELECTED, useGroupList } from './useGroupList'
import { __clearTaxonomicResourceCache } from './useTaxonomicResource'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: { get: jest.fn() },
}))

const apiGet = api.get as jest.MockedFunction<typeof api.get>

function makeGroup(overrides: Partial<TaxonomicFilterGroup> = {}): TaxonomicFilterGroup {
    return {
        name: 'Events',
        searchPlaceholder: 'events',
        type: TaxonomicFilterGroupType.Events,
        getName: (item: any) => item.name,
        getValue: (item: any) => item.name,
        getPopoverHeader: () => 'Event',
        ...overrides,
    } as TaxonomicFilterGroup
}

describe('useGroupList', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
        apiGet.mockReset()
    })

    afterEach(() => cleanup())

    describe('local-only group (no endpoint)', () => {
        it('returns rawLocalItems when no search', () => {
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Wildcards,
                options: [{ name: 'foo' }, { name: 'bar' }] as any,
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '' }))
            expect(result.current.items.map((i: any) => i.name)).toEqual(['foo', 'bar'])
            expect(result.current.totalResultCount).toBe(2)
            expect(result.current.hasRemoteDataSource).toBe(false)
            expect(result.current.isLoading).toBe(false)
        })

        it('Fuse-filters local items by search query', () => {
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Wildcards,
                options: [{ name: 'apple' }, { name: 'banana' }, { name: 'apricot' }] as any,
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: 'app' }))
            const names = result.current.items.map((i: any) => i.name)
            expect(names).toContain('apple')
            expect(names).not.toContain('banana')
        })

        it('uses optionsFromProp when group has no options', () => {
            const group = makeGroup({ type: TaxonomicFilterGroupType.Metadata })
            const { result } = renderHook(() =>
                useGroupList({
                    group,
                    searchQuery: '',
                    optionsFromProp: { [TaxonomicFilterGroupType.Metadata]: [{ name: 'm1' }, { name: 'm2' }] },
                })
            )
            expect(result.current.items.map((i: any) => i.name)).toEqual(['m1', 'm2'])
        })

        it('uses localOverride when provided (orchestrator path)', () => {
            const group = makeGroup({ type: TaxonomicFilterGroupType.Actions })
            const { result } = renderHook(() =>
                useGroupList({
                    group,
                    searchQuery: '',
                    localOverride: [{ name: 'override-action' }] as any,
                })
            )
            expect(result.current.items.map((i: any) => i.name)).toEqual(['override-action'])
        })

        it('honours group.localItemsSearch override', () => {
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Logs,
                options: [{ name: 'msg-1' }, { name: 'msg-2' }] as any,
                localItemsSearch: (items, q) => (q ? [{ name: 'custom: ' + q } as any, ...items] : items),
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: 'hello' }))
            expect((result.current.items[0] as any).name).toBe('custom: hello')
        })
    })

    describe('remote-only group', () => {
        it('fetches via the endpoint and exposes results', async () => {
            apiGet.mockResolvedValueOnce({ results: [{ name: 'remote-1' }, { name: 'remote-2' }], count: 2 })
            const group = makeGroup({ endpoint: 'api/projects/1/event_definitions' })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '' }))
            expect(result.current.isLoading).toBe(true)
            await waitFor(() => expect(result.current.totalResultCount).toBe(2))
            expect(result.current.items.map((i: any) => i.name)).toEqual(['remote-1', 'remote-2'])
            expect(result.current.isLoading).toBe(false)
        })

        it('respects minSearchQueryLength gating', () => {
            const group = makeGroup({
                endpoint: 'api/projects/1/whatever',
                minSearchQueryLength: 3,
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: 'ab' }))
            expect(result.current.needsMoreSearchCharacters).toBe(true)
            expect(result.current.isLoading).toBe(false)
            expect(apiGet).not.toHaveBeenCalled()
        })

        it('refires when searchQuery changes', async () => {
            apiGet
                .mockResolvedValueOnce({ results: [{ name: 'a' }], count: 1 })
                .mockResolvedValueOnce({ results: [{ name: 'b' }], count: 1 })
            const group = makeGroup({ endpoint: 'api/projects/1/event_definitions' })
            const { result, rerender } = renderHook(({ q }: { q: string }) => useGroupList({ group, searchQuery: q }), {
                initialProps: { q: '' },
            })
            await waitFor(() => expect((result.current.items[0] as any).name).toBe('a'))
            rerender({ q: 'x' })
            await waitFor(() => expect((result.current.items[0] as any).name).toBe('b'))
            expect(apiGet).toHaveBeenCalledTimes(2)
        })

        it('exposes expandable state when scoped + expandedCount > count', async () => {
            apiGet
                // primary scoped fetch
                .mockResolvedValueOnce({ results: [{ name: 's' }], count: 1 })
                // extra full count fetch
                .mockResolvedValueOnce({ count: 9 })
            const group = makeGroup({
                endpoint: 'api/projects/1/property_definitions',
                scopedEndpoint: 'api/projects/1/property_definitions?scoped',
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '' }))
            await waitFor(() => expect(result.current.totalResultCount).toBe(1))
            expect(result.current.isExpandable).toBe(true)
            expect(result.current.rowCount).toBe(2) // results + expand button
        })

        it('expand() switches to the unscoped endpoint and refetches', async () => {
            apiGet
                // initial scoped: 1 result
                .mockResolvedValueOnce({ results: [{ name: 's' }], count: 1 })
                .mockResolvedValueOnce({ count: 9 })
                // after expand: 9 results
                .mockResolvedValueOnce({ results: Array.from({ length: 9 }, (_, i) => ({ name: `r${i}` })), count: 9 })
            const group = makeGroup({
                endpoint: 'api/projects/1/property_definitions',
                scopedEndpoint: 'api/projects/1/property_definitions?scoped',
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '' }))
            await waitFor(() => expect(result.current.totalResultCount).toBe(1))
            act(() => result.current.expand())
            await waitFor(() => expect(result.current.totalResultCount).toBe(9))
        })
    })

    describe('keyword shortcuts', () => {
        it('prepends QuickFilterItems when enabled and group provides shortcuts', () => {
            const shortcut: QuickFilterItem = {
                _type: 'quick_filter',
                name: 'click (autocapture)',
                filterValue: 'click',
                operator: PropertyOperator.Exact,
                propertyKey: '$event_type',
                propertyFilterType: PropertyFilterType.Event,
            }
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Events,
                options: [{ name: 'click_event' }] as any,
                keywordShortcuts: () => [shortcut],
            })
            const { result } = renderHook(() =>
                useGroupList({ group, searchQuery: 'click', enableKeywordShortcuts: true })
            )
            // Shortcut comes first, then the Fuse-matched local item.
            expect(result.current.items[0]).toBe(shortcut)
            expect((result.current.items[1] as any).name).toBe('click_event')
        })

        it('skips shortcuts when enableKeywordShortcuts is false', () => {
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Events,
                options: [{ name: 'real' }] as any,
                keywordShortcuts: () => [
                    {
                        _type: 'quick_filter',
                        name: 'k',
                        filterValue: 'k',
                        operator: PropertyOperator.Exact,
                        propertyKey: '$event_type',
                        propertyFilterType: PropertyFilterType.Event,
                    },
                ],
            })
            // No search → no Fuse filtering, no shortcut prepend.
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '' }))
            expect(result.current.items.map((i: any) => i.name)).toEqual(['real'])
        })
    })

    describe('keyboard navigation', () => {
        it('moveDown wraps around', () => {
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Wildcards,
                options: [{ name: 'a' }, { name: 'b' }, { name: 'c' }] as any,
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '' }))
            expect(result.current.index).toBe(0)
            act(() => result.current.moveDown())
            expect(result.current.index).toBe(1)
            act(() => result.current.moveDown())
            expect(result.current.index).toBe(2)
            act(() => result.current.moveDown())
            expect(result.current.index).toBe(0)
        })

        it('moveUp wraps backwards', () => {
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Wildcards,
                options: [{ name: 'a' }, { name: 'b' }, { name: 'c' }] as any,
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '' }))
            act(() => result.current.moveUp())
            expect(result.current.index).toBe(2)
        })

        it('selectFirstItem=false starts at NO_ITEM_SELECTED', () => {
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Wildcards,
                options: [{ name: 'a' }] as any,
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '', selectFirstItem: false }))
            expect(result.current.index).toBe(NO_ITEM_SELECTED)
        })
    })

    describe('empty / loading states', () => {
        it('local-only with no items + search shows empty state', () => {
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Wildcards,
                options: [{ name: 'apple' }] as any,
            })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: 'zzz' }))
            expect(result.current.totalResultCount).toBe(0)
            expect(result.current.showEmptyState).toBe(true)
        })

        it('remote group with no search and no remote data shows loading then settles', async () => {
            apiGet.mockResolvedValueOnce({ results: [], count: 0 })
            const group = makeGroup({ endpoint: 'api/projects/1/event_definitions' })
            const { result } = renderHook(() => useGroupList({ group, searchQuery: '' }))
            expect(result.current.showLoadingState).toBe(true)
            await waitFor(() => expect(result.current.isLoading).toBe(false))
        })

        it('allowNonCapturedEvents surfaces the option for empty Events search', async () => {
            apiGet.mockResolvedValueOnce({ results: [], count: 0 })
            const group = makeGroup({
                type: TaxonomicFilterGroupType.Events,
                endpoint: 'api/projects/1/event_definitions',
            })
            const { result } = renderHook(() =>
                useGroupList({ group, searchQuery: 'unseen', allowNonCapturedEvents: true })
            )
            await waitFor(() => expect(result.current.isLoading).toBe(false))
            expect(result.current.showNonCapturedEventOption).toBe(true)
        })
    })
})
