import { act, cleanup, renderHook } from '@testing-library/react'
import { Provider } from 'kea'
import { ReactNode } from 'react'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { TaxonomicFilterGroupType } from '../types'
import { useTaxonomicFilter } from './useTaxonomicFilter'
import { __clearTaxonomicResourceCache } from './useTaxonomicResource'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('lib/api', () => ({
    __esModule: true,
    default: { get: jest.fn().mockResolvedValue({ results: [], count: 0 }) },
}))

const wrapper = ({ children }: { children: ReactNode }): JSX.Element => <Provider>{children}</Provider>

describe('useTaxonomicFilter', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
        useMocks({
            get: { '/api/projects/:team/event_definitions': { results: [], count: 0 } },
            post: { '/api/environments/:team/query': { results: [] } },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => cleanup())

    it('exposes groups in the consumer-requested order, with Recent/Pinned auto-injected', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                        TaxonomicFilterGroupType.PersonProperties,
                    ],
                }),
            { wrapper }
        )
        // SuggestedFilters leads (rebuilt menu always surfaces "All" for a multi-content
        // picker), then Recent + Pinned auto-inject.
        expect(result.current.groupTypes).toEqual([
            TaxonomicFilterGroupType.SuggestedFilters,
            TaxonomicFilterGroupType.RecentFilters,
            TaxonomicFilterGroupType.PinnedFilters,
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.PersonProperties,
        ])
        expect(result.current.groups.map((g) => g.type)).toEqual(result.current.groupTypes)
    })

    it.each([
        {
            name: 'does not auto-inject SuggestedFilters for a single content group',
            requested: [TaxonomicFilterGroupType.Events],
        },
        {
            name: 'does not auto-inject SuggestedFilters for a meta-only picker',
            requested: [TaxonomicFilterGroupType.HogQLExpression],
        },
        {
            name: 'does not auto-inject SuggestedFilters when a mutually-exclusive pair collapses',
            requested: [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.PageviewEvents],
        },
    ])('$name', ({ requested }) => {
        const { result } = renderHook(() => useTaxonomicFilter({ taxonomicGroupTypes: requested }), { wrapper })
        expect(result.current.groupTypes).not.toContain(TaxonomicFilterGroupType.SuggestedFilters)
    })

    // Mirrors the legacy `taxonomicGroupTypes` selector cases in taxonomicFilterLogic.test.ts —
    // both surfaces must lead with the sole group, then Recent/Pinned, and drop any prepended All.
    it.each([
        {
            name: 'single substantive group leads, Recent/Pinned follow (no All)',
            requested: [TaxonomicFilterGroupType.Events],
        },
        {
            name: 'single substantive group drops an explicitly-prepended All and still leads',
            requested: [TaxonomicFilterGroupType.SuggestedFilters, TaxonomicFilterGroupType.Events],
        },
    ])('$name', ({ requested }) => {
        const { result } = renderHook(() => useTaxonomicFilter({ taxonomicGroupTypes: requested }), { wrapper })
        expect(result.current.groupTypes).toEqual([
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.RecentFilters,
            TaxonomicFilterGroupType.PinnedFilters,
        ])
    })

    it('auto-injects SuggestedFilters as the default for a multi-content picker', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.PersonProperties],
                }),
            { wrapper }
        )
        expect(result.current.groupTypes).toContain(TaxonomicFilterGroupType.SuggestedFilters)
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.SuggestedFilters)
    })

    it('SuggestedFilters injected by a late-growing group list becomes the default', () => {
        const { result, rerender } = renderHook(
            ({ types }: { types: TaxonomicFilterGroupType[] }) => useTaxonomicFilter({ taxonomicGroupTypes: types }),
            { wrapper, initialProps: { types: [TaxonomicFilterGroupType.Events] } }
        )
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Events)

        rerender({ types: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.PersonProperties] })

        expect(result.current.groupTypes).toContain(TaxonomicFilterGroupType.SuggestedFilters)
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.SuggestedFilters)
    })

    it('an explicit choice survives the group list growing', () => {
        const { result, rerender } = renderHook(
            ({ types }: { types: TaxonomicFilterGroupType[] }) => useTaxonomicFilter({ taxonomicGroupTypes: types }),
            { wrapper, initialProps: { types: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions] } }
        )
        act(() => result.current.setActiveGroupType(TaxonomicFilterGroupType.Actions))

        rerender({
            types: [
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.PersonProperties,
            ],
        })

        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Actions)
    })

    it('initial groupType prop is respected', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.PersonProperties],
                    groupType: TaxonomicFilterGroupType.Events,
                }),
            { wrapper }
        )
        // SuggestedFilters is auto-injected for the multi-content picker, but the explicit
        // initial groupType still wins as the active tab.
        expect(result.current.groupTypes).toContain(TaxonomicFilterGroupType.SuggestedFilters)
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Events)
    })

    it('defaults to the first non-meta group when SuggestedFilters is not present', () => {
        const { result } = renderHook(
            () => useTaxonomicFilter({ taxonomicGroupTypes: [TaxonomicFilterGroupType.Events] }),
            { wrapper }
        )
        expect(result.current.groupTypes).not.toContain(TaxonomicFilterGroupType.SuggestedFilters)
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Events)
    })

    it('defaults activeGroupType to props.groupType when valid', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                    groupType: TaxonomicFilterGroupType.Actions,
                }),
            { wrapper }
        )
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Actions)
    })

    it('falls back to SuggestedFilters when present, otherwise first non-meta', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    // Two substantive groups so "All" is retained — a single substantive group drops it
                    taxonomicGroupTypes: [
                        TaxonomicFilterGroupType.SuggestedFilters,
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                    ],
                }),
            { wrapper }
        )
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.SuggestedFilters)
    })

    it('updates active group via setActiveGroupType when included', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                }),
            { wrapper }
        )
        act(() => result.current.setActiveGroupType(TaxonomicFilterGroupType.Actions))
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Actions)
    })

    it('ignores setActiveGroupType requests for unavailable types', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                }),
            { wrapper }
        )
        act(() => result.current.setActiveGroupType(TaxonomicFilterGroupType.Cohorts))
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Events)
    })

    it('tabLeft / tabRight cycle through visible groups', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                        TaxonomicFilterGroupType.PersonProperties,
                    ],
                    groupType: TaxonomicFilterGroupType.Events,
                }),
            { wrapper }
        )
        act(() => result.current.tabRight())
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Actions)
        act(() => result.current.tabRight())
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.PersonProperties)
        act(() => result.current.tabRight()) // already at last; no-op
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.PersonProperties)
        act(() => result.current.tabLeft())
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Actions)
    })

    it('uncontrolled search query mutates via setSearchQuery', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                }),
            { wrapper }
        )
        expect(result.current.searchQuery).toBe('')
        act(() => result.current.setSearchQuery('hello'))
        expect(result.current.searchQuery).toBe('hello')
    })

    it('controlled search query notifies via onSearchQueryChange and reflects prop', () => {
        const onSearchQueryChange = jest.fn()
        const { result, rerender } = renderHook(
            ({ q }: { q: string }) =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                    searchQuery: q,
                    onSearchQueryChange,
                }),
            { wrapper, initialProps: { q: 'init' } }
        )
        expect(result.current.searchQuery).toBe('init')
        act(() => result.current.setSearchQuery('typed'))
        expect(onSearchQueryChange).toHaveBeenCalledWith('typed')
        // controlled — internal state is not updated; consumer must re-render with new prop.
        expect(result.current.searchQuery).toBe('init')
        rerender({ q: 'typed' })
        expect(result.current.searchQuery).toBe('typed')
    })

    it('selectItem invokes onChange and clears the search query', () => {
        const onChange = jest.fn()
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                    onChange,
                    initialSearchQuery: 'foo',
                }),
            { wrapper }
        )
        const eventsGroup = result.current.groups.find((g) => g.type === TaxonomicFilterGroupType.Events)!
        act(() => result.current.selectItem(eventsGroup, 'evt', { name: 'evt' }))
        expect(onChange).toHaveBeenCalledWith(eventsGroup, 'evt', { name: 'evt' })
        expect(result.current.searchQuery).toBe('')
    })

    it('Escape key clears search', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                    initialSearchQuery: 'wat',
                }),
            { wrapper }
        )
        act(() =>
            result.current.rootProps.onKeyDown({
                key: 'Escape',
                preventDefault: jest.fn(),
            } as any)
        )
        expect(result.current.searchQuery).toBe('')
    })

    it('Tab key advances active group; Shift+Tab moves back', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                    groupType: TaxonomicFilterGroupType.Events,
                }),
            { wrapper }
        )
        act(() =>
            result.current.rootProps.onKeyDown({
                key: 'Tab',
                shiftKey: false,
                preventDefault: jest.fn(),
            } as any)
        )
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Actions)
        act(() =>
            result.current.rootProps.onKeyDown({
                key: 'Tab',
                shiftKey: true,
                preventDefault: jest.fn(),
            } as any)
        )
        expect(result.current.activeGroupType).toBe(TaxonomicFilterGroupType.Events)
    })

    it('Enter forwards to onEnter when no list is registered', () => {
        const onEnter = jest.fn()
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                    onEnter,
                    initialSearchQuery: 'q',
                }),
            { wrapper }
        )
        act(() =>
            result.current.rootProps.onKeyDown({
                key: 'Enter',
                preventDefault: jest.fn(),
            } as any)
        )
        expect(onEnter).toHaveBeenCalledWith('q')
    })

    it('Enter selects via the registered active list when present', () => {
        const onChange = jest.fn()
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                    onChange,
                }),
            { wrapper }
        )
        const eventsGroup = result.current.activeGroup!
        const fakeItem = { id: 42, name: 'pageview' }
        const fakeApi = {
            items: [fakeItem] as any,
            rowCount: 1,
            totalResultCount: 1,
            index: 0,
            setIndex: jest.fn(),
            moveUp: jest.fn(),
            moveDown: jest.fn(),
            itemAtIndex: () => fakeItem as any,
            isLoading: false,
            isFetching: false,
            needsMoreSearchCharacters: false,
            hasRemoteDataSource: false,
            showEmptyState: false,
            showLoadingState: false,
            showNonCapturedEventOption: false,
            isExpandable: false,
            isExpanded: false,
            expand: jest.fn(),
            refetch: jest.fn(),
        }
        act(() => result.current.registerActiveList(() => fakeApi))
        act(() =>
            result.current.rootProps.onKeyDown({
                key: 'Enter',
                preventDefault: jest.fn(),
            } as any)
        )
        // Events group.getValue returns .name for items with an `id`.
        expect(onChange).toHaveBeenCalledWith(eventsGroup, 'pageview', fakeItem)
    })

    it('searchPlaceholder composes label fragments from content groups only (Recent + Pinned excluded)', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                }),
            { wrapper }
        )
        // Recent + Pinned auto-inject as META groups but are excluded from
        // the placeholder — only content categories surface, joined into a
        // simple "events, actions" label since there are only 2.
        expect(result.current.searchPlaceholder).toBe('events, actions')
    })

    it('getGroupListInput returns shape compatible with useGroupList', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                    showNumericalPropsOnly: true,
                    enableKeywordShortcuts: true,
                }),
            { wrapper }
        )
        const eventsGroup = result.current.groups.find((g) => g.type === TaxonomicFilterGroupType.Events)!
        const input = result.current.getGroupListInput(eventsGroup)
        expect(input.group).toBe(eventsGroup)
        expect(input.searchQuery).toBe('')
        expect(input.showNumericalPropsOnly).toBe(true)
        expect(input.enableKeywordShortcuts).toBe(true)
    })
})
