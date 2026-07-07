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
import { TaxonomicDefinitionTypes, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
import { MenuFilterCombobox, SEARCH_QUERY_DEBOUNCE_MS } from './Combobox'
import { MenuFilterEntry } from './types'

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
    onCommit?: any
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
                    onCommit={options.onCommit ?? jest.fn()}
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

// The category Select popup portal — scoping option lookups here avoids matching
// row badges/labels that repeat the option text (e.g. "Recent", "Pinned").
async function openedCategoryPopup(): Promise<HTMLElement> {
    return await waitFor(() => {
        const popup = document.querySelector<HTMLElement>('[data-slot="select-content"]')
        if (!popup) {
            throw new Error('category select popup not open')
        }
        return popup
    })
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

    // Mirrors the synthetic entry built by `TaxonomicPopoverMenu` for an
    // already-selected event value (e.g. the trends series picker reopened on
    // "Pageview"). `value` is whatever the call site threads through — the raw
    // event key `$pageview` or, when `filter.name` holds the label, `Pageview`.
    // getValue returns name-or-id just like the adapter.
    function syntheticEventSelected(value: string): MenuFilterEntry {
        return {
            item: { id: value, name: value } as TaxonomicDefinitionTypes,
            // Deliberate partial — only the three fields the menu reads from a
            // synthetic selection. Cast (as the production adapter does) rather
            // than populate the full group shape. The `MenuFilterEntry` return
            // type is what keeps the entry contract compiler-checked.
            group: {
                type: TaxonomicFilterGroupType.Events,
                getName: (t) => t?.name,
                getValue: (t) => t?.name ?? t?.id,
            } as TaxonomicFilterGroup,
            name: value,
        }
    }

    function renderEventsWithSelection(options: {
        searchQuery?: string
        selectedEntry?: MenuFilterEntry
    }): ReturnType<typeof render> {
        return render(
            <Provider>
                <TaxonomicFilterHeadless.Root
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    onChange={jest.fn()}
                    searchQuery={options.searchQuery ?? ''}
                >
                    <MenuFilterCombobox
                        drillTo="all"
                        selectedEntry={options.selectedEntry}
                        onCommit={jest.fn()}
                        onBack={jest.fn()}
                    />
                </TaxonomicFilterHeadless.Root>
            </Provider>
        )
    }

    // The committed selection arrives as a synthetic entry whose value is
    // either the raw event key (`$pageview`) or — when `ActionFilterRow` threads
    // `filter.name` and that holds the display label — the friendly label
    // (`Pageview`). Both must collapse onto the real endpoint row instead of
    // stranding a placeholder beside it with a second checkmark and a blank
    // preview.
    it.each([
        ['the raw key', '$pageview'],
        ['the friendly label', 'Pageview'],
    ])(
        'dedups the synthetic selected event against the real endpoint event when the value is %s',
        async (_label, selectedValue) => {
            apiGet.mockImplementation((url: string) => {
                if (url.includes('event_definitions')) {
                    return Promise.resolve({
                        results: [
                            { id: 'def-1', name: '$pageview' },
                            { id: 'def-2', name: '$bot_pageview' },
                        ],
                        count: 2,
                    })
                }
                return Promise.resolve({ results: [], count: 0 })
            })

            renderEventsWithSelection({
                searchQuery: 'pagev',
                selectedEntry: syntheticEventSelected(selectedValue),
            })

            await waitFor(() => expect(rowTexts().some((t) => t.includes('$bot_pageview'))).toBe(true))
            // Exactly one "Pageview" row…
            const pageviewRows = rowTexts().filter((t) => t.includes('Pageview') && !t.includes('bot'))
            expect(pageviewRows).toHaveLength(1)
            // …and the surviving row is the real definition (carries the raw
            // `$pageview` value), not the synthetic placeholder (which would render
            // just the label with no raw value).
            expect(pageviewRows[0]).toContain('$pageview')
            // The selection resolves onto the real row so the checkmark + preview
            // track it: the real row's DOM id must exist to be targeted.
            expect(document.getElementById('menu-filter-row-events-$pageview')).toBeInTheDocument()
            // …and the synthetic placeholder row — the one that carried the
            // stray second checkmark in the bug — must not be rendered at all.
            expect(document.getElementById('menu-filter-row-events-Pageview')).not.toBeInTheDocument()
            // The preview pane picks up the real definition ("Sent as $pageview"),
            // not the synthetic placeholder (which has no core definition and so
            // renders neither a raw value nor a description).
            const preview = document.querySelector('[data-slot="menu-filter-preview"]')
            expect(preview?.textContent).toContain('Sent as')
            expect(preview?.textContent).toContain('$pageview')
        }
    )

    it('prefers an exact value match over the friendly-label heuristic when a custom event shares the label', async () => {
        // A custom event literally named "Pageview" coexists with core
        // "$pageview" (friendly label "Pageview"). A selection whose value is
        // "Pageview" must resolve to the custom event (exact value match), not
        // the core row it only label-matches — and both real rows stay (they're
        // distinct definitions), with no synthetic placeholder.
        apiGet.mockImplementation((url: string) => {
            if (url.includes('event_definitions')) {
                return Promise.resolve({
                    results: [
                        { id: 'def-core', name: '$pageview' },
                        { id: 'def-custom', name: 'Pageview' },
                    ],
                    count: 2,
                })
            }
            return Promise.resolve({ results: [], count: 0 })
        })

        renderEventsWithSelection({
            searchQuery: 'pagev',
            selectedEntry: syntheticEventSelected('Pageview'),
        })

        await waitFor(() => expect(document.getElementById('menu-filter-row-events-Pageview')).toBeInTheDocument())
        // Both distinct events render — the custom "Pageview" did not dedup the
        // core "$pageview" away, and no synthetic placeholder was prepended.
        expect(document.getElementById('menu-filter-row-events-$pageview')).toBeInTheDocument()
        const rows = Array.from(document.querySelectorAll('[data-slot="taxonomic-filter-menu-row"]'))
        expect(rows).toHaveLength(2)
        // The persistent selected tint (`bg-(--fill-hover)`, a discrete class
        // token distinct from the `data-selected:`-prefixed hover variant) lands
        // on the exact-match custom event, not the label-match core row.
        const customRow = document.getElementById('menu-filter-row-events-Pageview')
        const coreRow = document.getElementById('menu-filter-row-events-$pageview')
        expect(customRow?.classList.contains('bg-(--fill-hover)')).toBe(true)
        expect(coreRow?.classList.contains('bg-(--fill-hover)')).toBe(false)
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

    it('shows a complete recent as both a full value row and a separate bare key row', async () => {
        renderAll({
            groupTypes: [TaxonomicFilterGroupType.EventProperties],
            recentEntries: [
                {
                    ...makeEntry(TaxonomicFilterGroupType.EventProperties, '$browser', 'Event properties'),
                    recentPropertyFilter: { key: '$browser', operator: 'exact', value: 'Chrome' },
                    recentLabel: 'Browser = Chrome',
                },
                makeEntry(TaxonomicFilterGroupType.EventProperties, '$browser', 'Event properties'),
            ],
        })

        await waitFor(() => expect(rowTexts().length).toBeGreaterThan(0))
        const texts = rowTexts()
        expect(texts.some((t) => t.includes('Browser = Chrome'))).toBe(true)
        expect(texts.some((t) => t.includes('$browser') && !t.includes('Chrome'))).toBe(true)
    })

    it.each([
        ['email', '$email'],
        ['url', '$current_url'],
        ['path', '$pathname'],
    ])('floats the promoted property to the top of the content when searching %p', async (searchTerm, promotedName) => {
        apiGet.mockImplementation((url: string) => {
            if (url.includes('property_definitions')) {
                // The decoy is returned first so a passing assertion can only mean
                // promotion reordered the result, not the server order.
                return Promise.resolve({
                    results: [
                        { id: 1, name: 'other_prop' },
                        { id: 2, name: promotedName },
                    ],
                    count: 2,
                })
            }
            return Promise.resolve({ results: [], count: 0 })
        })

        renderAll({ groupTypes: [TaxonomicFilterGroupType.EventProperties], searchQuery: searchTerm })

        await waitFor(() => expect(screen.getByText('other_prop')).toBeInTheDocument())
        const rows = rowTexts()
        const promotedIdx = rows.findIndex((t) => t.includes(promotedName))
        const otherIdx = rows.findIndex((t) => t.includes('other_prop'))
        expect(promotedIdx).toBeGreaterThanOrEqual(0)
        expect(promotedIdx).toBeLessThan(otherIdx)
    })

    describe('pageview URLs collapse to a single "contains" suggestion', () => {
        const mockUrlValues = (urls: string[]): void => {
            apiGet.mockImplementation((url: string) => {
                if (url.includes('events/values') && url.includes('current_url')) {
                    return Promise.resolve(urls.map((name) => ({ name })))
                }
                return Promise.resolve({ results: [], count: 0 })
            })
        }

        it('collapses matching URLs into one "URL contains <query>" row, not the raw URL list', async () => {
            mockUrlValues(['https://app.posthog.com/checkout', 'https://app.posthog.com/checkout/pay'])

            renderAll({ groupTypes: [TaxonomicFilterGroupType.PageviewUrls], searchQuery: 'checkout' })

            await waitFor(() => expect(rowTexts().some((t) => t.includes('URL contains "checkout"'))).toBe(true))
            const rows = rowTexts()
            // Exactly one synthetic row, and none of the raw matched URLs are listed.
            expect(rows.filter((t) => t.includes('URL contains "checkout"'))).toHaveLength(1)
            expect(rows.some((t) => t.includes('https://app.posthog.com/checkout'))).toBe(false)
        })

        it('shows no URL suggestion when no pageview URL matches (0 slots)', async () => {
            mockUrlValues([])

            renderAll({ groupTypes: [TaxonomicFilterGroupType.PageviewUrls], searchQuery: 'zzznomatch' })

            await waitFor(() => expect(screen.queryByTestId('menu-filter-loading')).not.toBeInTheDocument())
            expect(screen.queryByText(/URL contains/)).not.toBeInTheDocument()
        })

        it('does not offer Pageview URLs as a navigable category', async () => {
            const user = userEvent.setup()
            mockUrlValues(['https://app.posthog.com/checkout'])

            renderAll({
                groupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PageviewUrls],
            })

            await user.click(screen.getByLabelText('Filter category'))
            expect(within(await openedCategoryPopup()).queryByText('Pageview URLs')).not.toBeInTheDocument()
        })

        it('commits the typed query as the value so it becomes $current_url contains <query>', async () => {
            const user = userEvent.setup()
            const onCommit = jest.fn()
            mockUrlValues(['https://app.posthog.com/checkout'])

            renderAll({
                groupTypes: [TaxonomicFilterGroupType.PageviewUrls],
                searchQuery: 'checkout',
                onCommit,
            })

            await waitFor(() => expect(rowTexts().some((t) => t.includes('URL contains "checkout"'))).toBe(true))
            const row = Array.from(document.querySelectorAll('[data-slot="taxonomic-filter-menu-row"]')).find((el) =>
                el.textContent?.includes('URL contains "checkout"')
            ) as HTMLElement
            await user.click(row)

            const [entry] = onCommit.mock.calls[0]
            expect(entry.group.type).toBe(TaxonomicFilterGroupType.PageviewUrls)
            // getValue reads the item name; the synthetic row carries the query, which
            // `taxonomicPropertyFilterLogic.selectItem` turns into `$current_url IContains`.
            expect(entry.group.getValue(entry.item)).toBe('checkout')
            // Tagged so the commit telemetry can measure adoption of the shortcut.
            expect((entry.item as { isContainsShortcut?: boolean }).isContainsShortcut).toBe(true)
        })

        it('opens on the All scope when the committed selection is from the hidden Pageview URLs category', async () => {
            apiGet.mockImplementation((url: string) => {
                if (url.includes('property_definitions')) {
                    return Promise.resolve({ results: [{ id: 1, name: '$browser' }], count: 1 })
                }
                return Promise.resolve([])
            })
            // What TaxonomicPopoverMenu builds when reopening an existing
            // `$current_url icontains <value>` filter picked via the shortcut.
            const selectedEntry = makeEntry(TaxonomicFilterGroupType.PageviewUrls, 'checkout', 'Pageview URLs')

            render(
                <Provider>
                    <TaxonomicFilterHeadless.Root
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PageviewUrls,
                        ]}
                        onChange={jest.fn()}
                    >
                        <MenuFilterCombobox
                            drillTo="all"
                            selectedEntry={selectedEntry}
                            onCommit={jest.fn()}
                            onBack={jest.fn()}
                        />
                    </TaxonomicFilterHeadless.Root>
                </Provider>
            )

            // Stranded-scope regression: the category dropdown must read "All"
            // (pageview_urls is not a navigable option) and the All-surface
            // content must render rather than an empty hidden-category list.
            await waitFor(() => expect(rowTexts().some((t) => t.includes('$browser'))).toBe(true))
            expect(screen.getByLabelText('Filter category')).toHaveTextContent('All')
            // The committed selection stays reachable via the selected-entry prepend.
            expect(rowTexts().some((t) => t.includes('checkout'))).toBe(true)
        })
    })

    // Spec for the insight series picker (e.g. funnel steps include Pageview events):
    // opening the menu shows "All" with event-context recents/pinned; searching a term
    // that matches pageview URLs surfaces ONE "url contains <query>" shortcut as the very
    // first row — ahead of recents, pinned, and event rows. These fail today because the
    // series (PageviewEvents) group is not collapsed and the shortcut never leads the list.
    describe('pageview url-contains shortcut leads the series picker All surface', () => {
        const mockUrlValues = (urls: string[]): void => {
            apiGet.mockImplementation((url: string) => {
                if (url.includes('events/values') && url.includes('current_url')) {
                    return Promise.resolve(urls.map((name) => ({ name })))
                }
                return Promise.resolve({ results: [], count: 0 })
            })
        }

        it('defaults to the All scope with event-context recents and pinned shown', async () => {
            mockUrlValues([])
            renderAll({
                groupTypes: [TaxonomicFilterGroupType.PageviewEvents, TaxonomicFilterGroupType.Events],
                recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'recent_signup', 'Events')],
                pinnedEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'pinned_purchase', 'Events')],
            })

            await waitFor(() => expect(rowTexts().some((t) => t.includes('recent_signup'))).toBe(true))
            expect(rowTexts().some((t) => t.includes('pinned_purchase'))).toBe(true)
            expect(screen.getByLabelText('Filter category')).toHaveTextContent('All')
        })

        it('opens focused on All, not the selected item category, when an event is already selected', async () => {
            apiGet.mockResolvedValue({ results: [], count: 0 })
            // Reopening the series picker on an existing `$pageview` selection: the menu
            // should land on the "All" scope, not jump to the Events category.
            const selectedEntry = makeEntry(TaxonomicFilterGroupType.Events, '$pageview', 'Events')
            render(
                <Provider>
                    <TaxonomicFilterHeadless.Root
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                        onChange={jest.fn()}
                    >
                        <MenuFilterCombobox
                            drillTo="all"
                            selectedEntry={selectedEntry}
                            onCommit={jest.fn()}
                            onBack={jest.fn()}
                        />
                    </TaxonomicFilterHeadless.Root>
                </Provider>
            )

            const category = await screen.findByLabelText('Filter category')
            // Wait for the Select to paint its active-category label before asserting.
            await waitFor(() => expect(category.textContent || '').toMatch(/All|Events/))
            expect(category).toHaveTextContent('All')
            expect(category).not.toHaveTextContent('Events')
        })

        it('leads with the committed selection as the first row when idle (no search)', async () => {
            apiGet.mockResolvedValue({ results: [{ id: 1, name: 'autocapture' }], count: 1 })
            // Reopening on an existing selection: the user often just wants to check what's
            // chosen, so the committed value is the first row even ahead of recents.
            const selectedEntry = makeEntry(TaxonomicFilterGroupType.Events, 'my_current_event', 'Events')
            render(
                <Provider>
                    <TaxonomicFilterHeadless.Root
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                        onChange={jest.fn()}
                    >
                        <MenuFilterCombobox
                            drillTo="all"
                            selectedEntry={selectedEntry}
                            recentEntries={[makeEntry(TaxonomicFilterGroupType.Events, 'recent_event', 'Events')]}
                            onCommit={jest.fn()}
                            onBack={jest.fn()}
                        />
                    </TaxonomicFilterHeadless.Root>
                </Provider>
            )

            await waitFor(() => expect(rowTexts().some((t) => t.includes('my_current_event'))).toBe(true))
            expect(rowTexts()[0]).toContain('my_current_event')
        })

        it('puts the "url contains <query>" shortcut first, then recent, then pinned', async () => {
            mockUrlValues(['https://app.posthog.com/replay', 'https://app.posthog.com/replay/home'])
            renderAll({
                groupTypes: [TaxonomicFilterGroupType.PageviewEvents, TaxonomicFilterGroupType.Events],
                recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'replay_recent', 'Events')],
                pinnedEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'replay_pinned', 'Events')],
                searchQuery: 'replay',
            })

            // Wait on a stable post-search signal (a matching recent) so the ordering
            // assertions fail fast rather than timing out waiting for a row that never renders.
            await waitFor(() => expect(rowTexts().some((t) => t.includes('replay_recent'))).toBe(true))
            const rows = rowTexts()
            const shortcutIdx = rows.findIndex((t) => /contains/i.test(t) && /replay/i.test(t))
            const recentIdx = rows.findIndex((t) => t.includes('replay_recent'))
            const pinnedIdx = rows.findIndex((t) => t.includes('replay_pinned'))

            // The contains shortcut leads the whole list, ahead of recents/pinned/events.
            expect(shortcutIdx).toBe(0)
            // Assert both rows are actually present (findIndex returns -1 when absent) so a
            // regression that drops the recent/pinned row fails loudly, not on index arithmetic.
            expect(recentIdx).toBeGreaterThan(0)
            expect(pinnedIdx).toBeGreaterThan(recentIdx)
            // and the raw matched URLs are collapsed away into the single shortcut.
            expect(rows.some((t) => t.includes('https://app.posthog.com/replay'))).toBe(false)
        })
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

        await user.click(screen.getByLabelText('Filter category'))
        const popup = await openedCategoryPopup()
        expect(await within(popup).findByText('Recent')).toBeInTheDocument()
        expect(within(popup).getByText('Pinned')).toBeInTheDocument()
    })

    it('forwards row selection context on commit and does not emit the legacy event itself', async () => {
        const user = userEvent.setup()
        apiGet.mockResolvedValue({ results: [], count: 0 })
        const onCommit = jest.fn()

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Events],
            recentEntries: [makeEntry(TaxonomicFilterGroupType.Events, 'pageview', 'Events')],
            onCommit,
        })

        await waitFor(() => expect(document.querySelector('[data-slot="taxonomic-filter-menu-row"]')).toBeTruthy())
        await user.click(document.querySelector('[data-slot="taxonomic-filter-menu-row"]') as HTMLElement)

        expect(onCommit).toHaveBeenCalledWith(
            expect.objectContaining({ group: expect.objectContaining({ type: TaxonomicFilterGroupType.Events }) }),
            undefined,
            // groupType is undefined for the 'all' meta scope; the final-commit funnel
            // (TaxonomicFilterMenu) turns this context into the legacy event.
            {
                groupType: undefined,
                position: 0,
                wasFromRecents: true,
                wasFromPinnedList: false,
            }
        )
        // The combobox no longer fires the legacy event on row click — that moved to
        // the final-commit funnel so cancelable DWH table picks are not counted.
        expect(captureMock).not.toHaveBeenCalledWith('taxonomic filter item selected', expect.anything())
    })

    it('forwards wasFromPinnedList=true in the commit context for a pinned row', async () => {
        const user = userEvent.setup()
        apiGet.mockResolvedValue({ results: [], count: 0 })
        const onCommit = jest.fn()

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.EventProperties],
            pinnedEntries: [makeEntry(TaxonomicFilterGroupType.EventProperties, 'plan', 'Event properties')],
            onCommit,
        })

        await waitFor(() => expect(document.querySelector('[data-slot="taxonomic-filter-menu-row"]')).toBeTruthy())
        await user.click(document.querySelector('[data-slot="taxonomic-filter-menu-row"]') as HTMLElement)

        expect(onCommit).toHaveBeenCalledWith(
            expect.anything(),
            undefined,
            expect.objectContaining({ wasFromPinnedList: true, wasFromRecents: false })
        )
    })

    it('captures debounced `taxonomic_filter_search_query` for a typed query', async () => {
        // Fake timers only here — the rest of the suite drives real async via
        // userEvent/waitFor. Scoped so advancing the debounce is deterministic and
        // instant instead of blocking on a real 500 ms timeout.
        jest.useFakeTimers()
        try {
            apiGet.mockResolvedValue({ results: [], count: 0 })

            renderAll({ groupTypes: [TaxonomicFilterGroupType.Events], searchQuery: 'pageview' })

            await act(async () => {
                // Flush the data-fetch microtasks the debounce effect rides behind…
                await Promise.resolve()
                // …then fire the debounce timer.
                jest.advanceTimersByTime(SEARCH_QUERY_DEBOUNCE_MS)
            })

            expect(captureMock).toHaveBeenCalledWith(
                'taxonomic_filter_search_query',
                expect.objectContaining({
                    surface: 'rebuild-menu',
                    searchQuery: 'pageview',
                    inputMode: 'typed',
                    pastedFraction: 0,
                    // Stale events hidden by default → excludeStale reads true at search time.
                    excludeStale: true,
                })
            )
        } finally {
            jest.useRealTimers()
        }
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

    it('fires `taxonomic filter empty result` exactly once per scope+query (dedup)', async () => {
        apiGet.mockResolvedValue({ results: [], count: 0 })

        renderAll({ groupTypes: [TaxonomicFilterGroupType.Events], searchQuery: 'zzz_no_match' })

        await waitFor(() =>
            expect(captureMock).toHaveBeenCalledWith(
                'taxonomic filter empty result',
                expect.objectContaining({ searchQuery: 'zzz_no_match' })
            )
        )

        const emptyResultCalls = captureMock.mock.calls.filter(
            ([event, props]: [string, any]) =>
                event === 'taxonomic filter empty result' && props?.searchQuery === 'zzz_no_match'
        )
        expect(emptyResultCalls).toHaveLength(1)
    })

    it('re-fires empty result for a query revisited after a different one (last-key dedup, matches legacy)', async () => {
        apiGet.mockResolvedValue({ results: [], count: 0 })
        const emptyFor = (q: string): number =>
            captureMock.mock.calls.filter(
                ([event, props]: [string, any]) => event === 'taxonomic filter empty result' && props?.searchQuery === q
            ).length
        const tree = (q: string): JSX.Element => (
            <Provider>
                <TaxonomicFilterHeadless.Root
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    onChange={jest.fn()}
                    searchQuery={q}
                >
                    <MenuFilterCombobox drillTo="all" onCommit={jest.fn()} onBack={jest.fn()} />
                </TaxonomicFilterHeadless.Root>
            </Provider>
        )

        const { rerender } = render(tree('aaa'))
        await waitFor(() => expect(emptyFor('aaa')).toBe(1))

        rerender(tree('bbb'))
        await waitFor(() => expect(emptyFor('bbb')).toBe(1))

        // Returning to "aaa" re-fires — an unbounded set would have suppressed it.
        rerender(tree('aaa'))
        await waitFor(() => expect(emptyFor('aaa')).toBe(2))
    })

    it('hides stale events by default and refetches including them when the empty-state button is clicked', async () => {
        const user = userEvent.setup()
        apiGet.mockResolvedValue({ results: [], count: 0 })

        render(
            <Provider>
                <TaxonomicFilterHeadless.Root
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    onChange={jest.fn()}
                    searchQuery="zzz_no_match"
                >
                    <MenuFilterCombobox
                        drillTo={TaxonomicFilterGroupType.Events}
                        onCommit={jest.fn()}
                        onBack={jest.fn()}
                    />
                </TaxonomicFilterHeadless.Root>
            </Provider>
        )

        // Default: the events fetch hides stale definitions.
        await waitFor(() =>
            expect(apiGet.mock.calls.some(([url]: [string]) => url.includes('exclude_stale=true'))).toBe(true)
        )

        const callsBeforeOptIn = apiGet.mock.calls.length
        await user.click(await screen.findByText('Include stale events'))

        // Opting in emits the legacy toggle event…
        expect(captureMock).toHaveBeenCalledWith(
            'taxonomic filter include stale toggled',
            expect.objectContaining({ surface: 'rebuild-menu', includeStaleEvents: true })
        )

        // …and refetches the events list without the stale exclusion.
        await waitFor(() => {
            const newUrls: string[] = apiGet.mock.calls.slice(callsBeforeOptIn).map(([url]: [string]) => url)
            expect(newUrls.length).toBeGreaterThan(0)
            expect(newUrls.every((url: string) => !url.includes('exclude_stale=true'))).toBe(true)
        })
    })

    it('offers a jump to All when a single category comes up empty, and clicking it switches scope', async () => {
        const user = userEvent.setup()
        apiGet.mockResolvedValue({ results: [], count: 0 })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Cohorts, TaxonomicFilterGroupType.Events],
            searchQuery: 'zzz_no_match',
        })

        // Narrow to a single category so the cross-category jump becomes relevant
        await user.click(screen.getByLabelText('Filter category'))
        await user.click(await within(await openedCategoryPopup()).findByText('Cohorts'))

        const jumpButton = await screen.findByText('Check for results in other categories')
        await user.click(jumpButton)

        expect(captureMock).toHaveBeenCalledWith(
            'taxonomic filter menu category changed',
            expect.objectContaining({ toChip: 'all', via: 'empty-state' })
        )
        // Back on the All scope, the jump no longer applies
        await waitFor(() => {
            expect(screen.getByLabelText('Filter category')).toHaveTextContent('All')
            expect(screen.queryByText('Check for results in other categories')).not.toBeInTheDocument()
        })
    })

    it('does not offer the jump on the All scope', async () => {
        apiGet.mockResolvedValue({ results: [], count: 0 })

        renderAll({
            groupTypes: [TaxonomicFilterGroupType.Cohorts, TaxonomicFilterGroupType.Events],
            searchQuery: 'zzz_no_match',
        })

        await waitFor(() => expect(screen.getByTestId('menu-filter-empty')).toBeInTheDocument())
        expect(screen.queryByText('Check for results in other categories')).not.toBeInTheDocument()
    })

    describe('reveal barrier', () => {
        it('hides stale results during a refetch and reveals once it settles', async () => {
            const user = userEvent.setup()
            let resolveSecond: ((value: { results: any[]; count: number }) => void) | undefined
            apiGet.mockImplementation((url: string) => {
                if (!url.includes('property_definitions')) {
                    return Promise.resolve({ results: [], count: 0, next: null })
                }
                if (url.includes('search=alpha')) {
                    return Promise.resolve({ results: [{ id: 1, name: 'alpha_prop' }], count: 1 })
                }
                // The second query's fetch is held open so we can observe the barrier holding.
                return new Promise((resolve) => {
                    resolveSecond = resolve
                })
            })

            function Harness(): JSX.Element {
                const [query, setQuery] = useState('alpha')
                return (
                    <>
                        <button onClick={() => setQuery('beta')}>change-query</button>
                        <Provider>
                            <TaxonomicFilterHeadless.Root
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                onChange={jest.fn()}
                                searchQuery={query}
                            >
                                <MenuFilterCombobox drillTo="all" onCommit={jest.fn()} onBack={jest.fn()} />
                            </TaxonomicFilterHeadless.Root>
                        </Provider>
                    </>
                )
            }

            render(<Harness />)

            // First query settles -> its result is revealed.
            await waitFor(() => expect(rowTexts().some((t) => t.includes('alpha_prop'))).toBe(true))

            // Change query: the refetch is in flight. `keepPreviousData` means the stale
            // `alpha_prop` is still in the list data, but the barrier must hide it behind a
            // skeleton rather than leaking it (the bug this ports the legacy barrier to fix).
            await user.click(screen.getByText('change-query'))
            await waitFor(() => expect(screen.getByTestId('menu-filter-loading')).toBeInTheDocument())
            expect(rowTexts().some((t) => t.includes('alpha_prop'))).toBe(false)

            // Resolve the refetch -> barrier opens, the new result shows, skeleton gone.
            resolveSecond?.({ results: [{ id: 2, name: 'beta_prop' }], count: 1 })
            await waitFor(() => expect(rowTexts().some((t) => t.includes('beta_prop'))).toBe(true))
            expect(screen.queryByTestId('menu-filter-loading')).not.toBeInTheDocument()
        })
    })
})
