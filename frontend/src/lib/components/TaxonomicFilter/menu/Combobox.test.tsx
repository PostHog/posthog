import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
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

describe('MenuFilterCombobox loading vs empty state', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
        apiGet.mockReset()
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
})
