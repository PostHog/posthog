import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { useState } from 'react'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { TaxonomicFilterHeadless } from '../headless'
import { __clearTaxonomicResourceCache } from '../hooks/useTaxonomicResource'
import { TaxonomicFilterGroupType } from '../types'
import { MenuFilterCombobox } from './Combobox'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('lib/api', () => {
    const emptyPaginated = (): Promise<{ results: any[]; count: number; next: null }> =>
        Promise.resolve({ results: [], count: 0, next: null })
    return {
        __esModule: true,
        default: {
            get: jest.fn().mockImplementation(emptyPaginated),
            actions: { list: jest.fn().mockImplementation(emptyPaginated) },
            dataWarehouseSavedQueries: { list: jest.fn().mockImplementation(emptyPaginated) },
            dataWarehouseTables: { list: jest.fn().mockImplementation(emptyPaginated) },
            queryTabState: { list: jest.fn().mockImplementation(emptyPaginated) },
            dashboards: { list: jest.fn().mockImplementation(emptyPaginated) },
            cohorts: { listPaginated: jest.fn().mockImplementation(emptyPaginated) },
        },
    }
})

const apiGet = jest.requireMock('lib/api').default.get as jest.MockedFunction<any>
const captureMock = jest.requireMock('posthog-js').default.capture as jest.Mock

function renderCombobox(): ReturnType<typeof render> {
    return render(
        <Provider>
            <TaxonomicFilterHeadless.Root taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts]} onChange={jest.fn()}>
                <MenuFilterCombobox
                    drillTo={TaxonomicFilterGroupType.Cohorts}
                    onCommit={jest.fn()}
                    onBack={jest.fn()}
                />
            </TaxonomicFilterHeadless.Root>
        </Provider>
    )
}

function makeEntry(groupType: TaxonomicFilterGroupType, name: string, groupName: string): any {
    return {
        item: { name },
        group: { type: groupType, name: groupName, getName: (t: any) => t?.name, getValue: (t: any) => t?.name },
        name,
    }
}

function renderAll(options: {
    groupTypes: TaxonomicFilterGroupType[]
    recentEntries?: any[]
    pinnedEntries?: any[]
    searchQuery?: string
}): ReturnType<typeof render> {
    return render(
        <Provider>
            <TaxonomicFilterHeadless.Root
                taxonomicGroupTypes={options.groupTypes}
                onChange={jest.fn()}
                searchQuery={options.searchQuery ?? ''}
            >
                <MenuFilterCombobox
                    drillTo="all"
                    recentEntries={options.recentEntries}
                    pinnedEntries={options.pinnedEntries}
                    onCommit={jest.fn()}
                    onBack={jest.fn()}
                />
            </TaxonomicFilterHeadless.Root>
        </Provider>
    )
}

function rowTexts(): string[] {
    return Array.from(document.querySelectorAll('[data-slot="taxonomic-filter-menu-row"]')).map(
        (el) => el.textContent ?? ''
    )
}

describe('MenuFilterCombobox', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
        apiGet.mockReset()
        captureMock.mockClear()
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
        useMocks({})
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => cleanup())

    it('shows a loading skeleton while the cohorts fetch is in flight (not the empty state)', async () => {
        // Hold the request open so the component sees `isLoading=true`.
        let resolveFetch!: (value: { results: any[]; count: number }) => void
        apiGet.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveFetch = resolve
                })
        )

        renderCombobox()

        // While loading: skeleton present, no "No Cohorts found" copy.
        await waitFor(() => {
            expect(screen.getByTestId('menu-filter-loading')).toBeInTheDocument()
        })
        expect(screen.queryByTestId('menu-filter-empty')).not.toBeInTheDocument()
        expect(screen.queryByText(/No "Cohorts" found/)).not.toBeInTheDocument()

        // Resolve to an empty list: skeleton disappears, empty state takes over.
        resolveFetch({ results: [], count: 0 })
        await waitFor(() => {
            expect(screen.getByTestId('menu-filter-empty')).toBeInTheDocument()
        })
        expect(screen.queryByTestId('menu-filter-loading')).not.toBeInTheDocument()
        expect(within(screen.getByTestId('menu-filter-empty')).getByText(/No "Cohorts" found/)).toBeInTheDocument()
    })

    it('renders results once the fetch resolves with items', async () => {
        apiGet.mockResolvedValue({
            results: [
                { id: 1, name: 'Internal team' },
                { id: 2, name: 'Power users' },
            ],
            count: 2,
        })

        renderCombobox()

        await waitFor(() => {
            expect(screen.queryByTestId('menu-filter-loading')).not.toBeInTheDocument()
        })
        // Skeleton gone + empty state not shown — items must have rendered.
        expect(screen.queryByTestId('menu-filter-empty')).not.toBeInTheDocument()
        // Row text appears inside the result rows.
        expect(screen.getAllByText('Internal team').length).toBeGreaterThan(0)
        expect(screen.getAllByText('Power users').length).toBeGreaterThan(0)
    })

    it('dedups a synthetic selected entry against the real remote entry (no double checkmark)', async () => {
        apiGet.mockResolvedValue({
            results: [
                { id: 5, name: 'Internal team' },
                { id: 6, name: 'Power users' },
            ],
            count: 2,
        })

        // Simulate what TaxonomicPopoverMenu builds: a synthetic entry with
        // `name: String(value)` and a getValue that returns name-or-id. The
        // real Cohorts group returns `cohort.id` (number) — without string
        // coercion in the dedup check, both rows would render side by side.
        const syntheticSelected = {
            item: { id: '5', name: '5' },
            group: {
                type: TaxonomicFilterGroupType.Cohorts,
                getName: (t: any) => t?.name,
                getValue: (t: any) => t?.name ?? t?.id,
            },
            name: '5',
        } as any

        render(
            <Provider>
                <TaxonomicFilterHeadless.Root
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts]}
                    onChange={jest.fn()}
                >
                    <MenuFilterCombobox
                        drillTo={TaxonomicFilterGroupType.Cohorts}
                        selectedEntry={syntheticSelected}
                        onCommit={jest.fn()}
                        onBack={jest.fn()}
                    />
                </TaxonomicFilterHeadless.Root>
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getAllByText('Internal team').length).toBeGreaterThan(0)
        })
        const rowEls = document.querySelectorAll('[data-slot="taxonomic-filter-menu-row"]')
        expect(rowEls.length).toBe(2)
        // No row should be the synthetic placeholder ("5" / N/A) — the real
        // cohort with id 5 must absorb the selected state.
        const rowsText = Array.from(rowEls)
            .map((el) => el.textContent ?? '')
            .join('\n')
        expect(rowsText).toContain('Internal team')
        expect(rowsText).toContain('Power users')
    })

    it('caches the cohorts first page and filters typed queries locally (no per-keystroke refetch)', async () => {
        // Track every cohorts request — there must be exactly one even after
        // typing, because client-side fuse takes over after the first page.
        let cohortCalls = 0
        apiGet.mockImplementation((url: string) => {
            if (url.includes('/cohorts/')) {
                cohortCalls += 1
                return Promise.resolve({
                    results: [
                        { id: 1, name: 'Internal team' },
                        { id: 2, name: 'Power users' },
                        { id: 3, name: 'Zzzbeta cohort' },
                    ],
                    count: 3,
                })
            }
            return Promise.resolve({ results: [], count: 0 })
        })

        // Wrap in a stateful host so we can change the controlled
        // searchQuery without remounting the Root (a remount would reset
        // kea state and force a fresh request even with the cache fix).
        let setQuery!: (q: string) => void
        function Host(): JSX.Element {
            const [q, setQ] = useState('')
            setQuery = setQ
            return (
                <Provider>
                    <TaxonomicFilterHeadless.Root
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Cohorts]}
                        onChange={jest.fn()}
                        searchQuery={q}
                    >
                        <MenuFilterCombobox
                            drillTo={TaxonomicFilterGroupType.Cohorts}
                            onCommit={jest.fn()}
                            onBack={jest.fn()}
                        />
                    </TaxonomicFilterHeadless.Root>
                </Provider>
            )
        }

        render(<Host />)

        await waitFor(() => expect(cohortCalls).toBe(1))
        // Initial render shows all three items.
        await waitFor(() => expect(screen.getAllByText('Zzzbeta cohort').length).toBeGreaterThan(0))

        // Now "type" a query — fuse should filter the cached page in place.
        act(() => setQuery('zzzbeta'))

        await waitFor(() => {
            const rowsText = Array.from(document.querySelectorAll('[data-slot="taxonomic-filter-menu-row"]'))
                .map((el) => el.textContent ?? '')
                .join('\n')
            expect(rowsText).toContain('Zzzbeta cohort')
            expect(rowsText).not.toContain('Internal team')
            expect(rowsText).not.toContain('Power users')
        })

        // The crucial assertion — no additional fetch fired for the typed query.
        expect(cohortCalls).toBe(1)
    })

    it('leads the "All" surface with recents then pinned, above the content rows', async () => {
        apiGet.mockResolvedValue({ results: [{ id: 1, name: 'autocapture' }], count: 1 })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.EventProperties],
            recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'my_recent_event', 'Events')],
            pinnedEntries: [makeEntry(TaxonomicFilterGroupType.EventProperties, 'my_pinned_prop', 'Event properties')],
        })

        await waitFor(() => expect(rowTexts().some((t) => t.includes('autocapture'))).toBe(true))
        const rows = rowTexts()
        // Fixed, learnable order: recent first, pinned second, content after.
        expect(rows[0]).toContain('my_recent_event')
        expect(rows[1]).toContain('my_pinned_prop')
        const recentIdx = rows.findIndex((t) => t.includes('my_recent_event'))
        const contentIdx = rows.findIndex((t) => t.includes('autocapture'))
        expect(contentIdx).toBeGreaterThan(recentIdx)
    })

    it('shows a recent that is also in the catalog only once (deduped from content)', async () => {
        apiGet.mockResolvedValue({ results: [{ id: 1, name: 'pageview' }], count: 1 })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Events],
            recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'pageview', 'Events')],
        })

        await waitFor(() => expect(screen.getAllByText('pageview').length).toBeGreaterThan(0))
        const pageviewRows = rowTexts().filter((t) => t.includes('pageview'))
        expect(pageviewRows).toHaveLength(1)
    })

    it('floats $email to the top of the content when searching "email"', async () => {
        apiGet.mockImplementation((url: string) => {
            if (url.includes('property_definitions')) {
                return Promise.resolve({
                    results: [
                        { id: 1, name: 'other_prop' },
                        { id: 2, name: '$email' },
                    ],
                    count: 2,
                })
            }
            return Promise.resolve({ results: [], count: 0 })
        })

        renderAll({ groupTypes: [TaxonomicFilterGroupType.EventProperties], searchQuery: 'email' })

        await waitFor(() => expect(screen.getByText('other_prop')).toBeInTheDocument())
        const rows = rowTexts()
        const emailIdx = rows.findIndex((t) => t.includes('$email'))
        const otherIdx = rows.findIndex((t) => t.includes('other_prop'))
        expect(emailIdx).toBeGreaterThanOrEqual(0)
        expect(emailIdx).toBeLessThan(otherIdx)
    })

    it('drops the recents/pinned prefix once the query no longer matches them', async () => {
        apiGet.mockResolvedValue({ results: [{ id: 1, name: 'autocapture' }], count: 1 })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Events],
            recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'my_recent_event', 'Events')],
            searchQuery: 'zzz_no_match',
        })

        await waitFor(() => expect(screen.getAllByText('autocapture').length).toBeGreaterThan(0))
        // The recent does not match the query, so it must not lead the list.
        expect(screen.queryByText('my_recent_event')).not.toBeInTheDocument()
    })

    it('tags recents and pinned rows with their source recency', async () => {
        apiGet.mockResolvedValue({ results: [{ id: 1, name: 'autocapture' }], count: 1 })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Events],
            recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'my_recent_event', 'Events')],
            pinnedEntries: [makeEntry(TaxonomicFilterGroupType.EventProperties, 'my_pinned_prop', 'Event properties')],
        })

        await waitFor(() => expect(rowTexts().some((t) => t.includes('autocapture'))).toBe(true))
        const rows = rowTexts()
        // Recency shows as a right-side badge ("Recent" / "Pinned"); the source
        // group still reads as the row's category label.
        const recentRow = rows.find((t) => t.includes('my_recent_event'))
        const pinnedRow = rows.find((t) => t.includes('my_pinned_prop'))
        expect(recentRow).toContain('Recent')
        expect(recentRow).toContain('Events')
        expect(pinnedRow).toContain('Pinned')
        expect(pinnedRow).toContain('Event properties')
    })

    it('recent leads the list at row 0 even when content also matches the search query', async () => {
        // Endpoint returns a row that matches the same query as the recent.
        apiGet.mockImplementation((url: string) => {
            if (url.includes('event_definitions') || url.includes('property_definitions')) {
                return Promise.resolve({
                    results: [{ id: 1, name: 'signup' }],
                    count: 1,
                })
            }
            return Promise.resolve({ results: [], count: 0 })
        })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Events],
            recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'signup', 'Events')],
            searchQuery: 'signup',
        })

        await waitFor(() => expect(rowTexts().some((t) => t.includes('signup'))).toBe(true))
        // The recent prefix must still be at index 0 — it leads even when
        // the content list also matches the query.
        expect(rowTexts()[0]).toContain('signup')
    })

    it('exposes Recent and Pinned as category options in the dropdown', async () => {
        const user = userEvent.setup()
        apiGet.mockResolvedValue({ results: [], count: 0 })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Events],
            recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'r', 'Events')],
            pinnedEntries: [makeEntry(TaxonomicFilterGroupType.EventProperties, 'p', 'Event properties')],
        })

        await user.click(screen.getByRole('combobox', { name: 'Filter category' }))
        expect(await screen.findByRole('option', { name: 'Recent' })).toBeInTheDocument()
        expect(screen.getByRole('option', { name: 'Pinned' })).toBeInTheDocument()
    })

    it('captures `taxonomic filter item selected` with the legacy contract on row click', async () => {
        const user = userEvent.setup()
        apiGet.mockResolvedValue({ results: [], count: 0 })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Events],
            recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'pageview', 'Events')],
        })

        await waitFor(() => expect(document.querySelector('[data-slot="taxonomic-filter-menu-row"]')).toBeTruthy())
        await user.click(document.querySelector('[data-slot="taxonomic-filter-menu-row"]') as HTMLElement)

        expect(captureMock).toHaveBeenCalledWith(
            'taxonomic filter item selected',
            expect.objectContaining({
                sourceGroupType: TaxonomicFilterGroupType.Events,
                wasFromRecents: true,
                wasFromPinnedList: false,
                wasQuickFilter: false,
                hadSearchInput: false,
                position: 0,
            })
        )
    })

    it('captures debounced `taxonomic_filter_search_query` for a typed query', async () => {
        apiGet.mockResolvedValue({ results: [], count: 0 })

        renderAll({ groupTypes: [TaxonomicFilterGroupType.Events], searchQuery: 'pageview' })

        await waitFor(() =>
            expect(captureMock).toHaveBeenCalledWith(
                'taxonomic_filter_search_query',
                expect.objectContaining({ searchQuery: 'pageview', inputMode: 'typed', pastedFraction: 0 })
            )
        )
    })

    it('captures `taxonomic filter empty result` for a no-match search', async () => {
        apiGet.mockResolvedValue({ results: [], count: 0 })

        renderAll({ groupTypes: [TaxonomicFilterGroupType.Events], searchQuery: 'zzz_no_match' })

        await waitFor(() =>
            expect(captureMock).toHaveBeenCalledWith(
                'taxonomic filter empty result',
                expect.objectContaining({ searchQuery: 'zzz_no_match' })
            )
        )
    })
})
