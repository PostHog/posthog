import { router } from 'kea-router'

import { searchListsLogic } from 'lib/components/Search/searchListsLogic'

import type { SettingSectionId } from '~/scenes/settings/types'
import { initKeaTests } from '~/test/init'

import { commandKSearchLogic } from './commandKSearchLogic'
import type { RemoteResults } from './commandKSources'

describe('commandKSearchLogic', () => {
    let logic: ReturnType<typeof commandKSearchLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = commandKSearchLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    test.each([
        ['typing', (): void => logic.actions.inputChanged('revenue', 7, false)],
        ['clearing the input', (): void => logic.actions.clearQuery()],
        ['removing a chip', (): void => logic.actions.applyKeyIntent({ type: 'remove-chip', index: 0 })],
    ])('a new query from %s drops the remembered highlight and collapses expanded groups', (_, changeQuery) => {
        logic.actions.setChipsAndText([{ key: 'is', value: 'dashboard', label: 'Dashboard', negated: false }], 'rev', 3)
        logic.actions.setHighlightedKey('recents/dashboard:1')
        logic.actions.activateRow(
            { kind: 'expand', key: 'group-settings/expand', group: 'settings', label: 'Show all 11 settings' },
            false,
            'enter'
        )
        expect(logic.values.expandedGroups).toEqual(['settings'])

        changeQuery()

        expect(logic.values.highlightedKey).toBeNull()
        expect(logic.values.expandedGroups).toEqual([])
    })

    test.each([
        ['retries a query whose request failed', true, undefined],
        ['reuses a query whose request answered', false, []],
    ])('%s when it is searched again', (_, failed, cached) => {
        logic.actions.remoteLoaded('ada', { persons: { items: [] } }, failed)
        const remoteBefore = logic.values.remote

        logic.actions.requestsStarted({ persons: 'ada', objects: 'ada' })

        expect(logic.values.remote.persons.cache['ada']).toEqual(cached)
        expect(logic.values.remote === remoteBefore).toBe(!failed)
    })

    it('remembers which persons query has more matches, and forgets it when the query loads again without', () => {
        logic.actions.remoteLoaded('ada', { persons: { items: [], more: true } })
        expect(logic.values.remote.persons.more).toEqual({ ada: true })

        logic.actions.remoteLoaded('ada', { persons: { items: [] } })
        expect(logic.values.remote.persons.more).toEqual({})
    })

    it('keeps the See all persons row when a search returns to a query it already loaded', () => {
        logic.actions.remoteLoaded('ada', { persons: { items: [], more: true } })

        logic.actions.inputChanged('ada', 3, false)

        expect(logic.values.remoteQueries.persons).toBe('ada')
        expect(logic.values.remote.persons.more).toEqual({ ada: true })
    })

    it('arrow up from the first row returns to the input, and arrow down stops at the last row', () => {
        const rows = logic.values.selectableRows
        expect(rows.length).toBeGreaterThan(1)

        logic.actions.applyKeyIntent({ type: 'move', direction: -1 })
        expect(logic.values.highlightedRow).toBeNull()

        logic.actions.applyKeyIntent({ type: 'move', direction: 1 })
        expect(logic.values.highlightedRow).toBe(rows[0])

        logic.actions.setHighlightedKey(rows[rows.length - 1].key)
        logic.actions.applyKeyIntent({ type: 'move', direction: 1 })
        expect(logic.values.highlightedRow).toBe(rows[rows.length - 1])
    })

    test.each([
        ['answered with nothing', false, { from: 'zzq_xyw', to: 'zzq xyw' }],
        ['answered, but one failed', true, null],
    ])('corrects a search only after every source %s', (_, oneFailed, expected) => {
        logic.actions.inputChanged('zzq_xyw', 7, false)
        const sources = Object.keys(logic.values.remoteQueries)
        expect(sources.length).toBeGreaterThan(1)

        logic.actions.remoteLoaded('zzq_xyw', { results: { items: [] } })
        expect(logic.values.searchCorrection).toBeNull()

        sources.forEach((source, index) => {
            logic.actions.remoteLoaded(
                'zzq_xyw',
                { [source]: { items: [] } } as RemoteResults,
                oneFailed && index === sources.length - 1
            )
        })
        expect(logic.values.searchCorrection).toEqual(expected)
    })

    it('searches a correction until the text changes', () => {
        logic.actions.inputChanged('zzq_xyw', 7, false)
        logic.actions.applyCorrection({ from: 'zzq_xyw', to: 'zzq xyw' })

        expect(logic.values.localQuery).toEqual('zzq xyw')
        expect(logic.values.requestQueries.objects).toEqual('zzq xyw')

        logic.actions.setChipsAndText([{ key: 'is', value: 'insight', label: 'Insight', negated: false }], 'zzq_xyw', 8)
        expect(logic.values.requestQueries.objects).toEqual('type:insight zzq xyw')

        logic.actions.setChipsAndText([], 'zzq_xywx', 8)

        expect(logic.values.localQuery).toEqual('zzq_xywx')
    })

    it('a See all row narrows the search to its type and keeps the words', () => {
        logic.actions.inputChanged('revenue', 7, false)

        logic.actions.activateRow(
            { kind: 'scope', key: 'group-insight/see-all', type: 'insight', label: 'See all insights' },
            false,
            'click'
        )

        expect(logic.values.chips).toEqual([expect.objectContaining({ key: 'is', value: 'insight', negated: false })])
        expect(logic.values.text).toEqual('revenue')
    })

    it('moves the highlight to the first new setting when a Show all row from an earlier render is clicked', () => {
        searchListsLogic({ commandPalette: true }).actions.setSettingsMap(
            Array.from({ length: 10 }, (_, index) => ({
                id: `user-zebra-${index}` as SettingSectionId,
                level: 'user' as const,
                title: `Zebra ${index}`,
                settings: [],
            }))
        )
        logic.actions.inputChanged('zebra', 5, false)
        const query = logic.values.remoteQueries.results as string
        logic.actions.remoteLoaded(query, {
            results: {
                items: [
                    {
                        id: 'dashboard-1',
                        name: 'Zebra board',
                        category: 'results',
                        record: { type: 'dashboard', ref: '1' },
                        rankKey: [-1, 0, 0, 0, -1, 0, 1, 0, 0],
                    },
                ],
            },
        })
        const renderedRow = logic.values.selectableRows.find((row) => row.kind === 'expand')
        expect(renderedRow).toBeTruthy()
        const index = logic.values.selectableRows.indexOf(renderedRow!)

        logic.actions.remoteLoaded(query, { persons: { items: [] } })
        expect(logic.values.selectableRows).not.toContain(renderedRow)
        logic.actions.activateRow(renderedRow!, false, 'click')

        const revealed = logic.values.selectableRows[index]
        expect(revealed).toMatchObject({ kind: 'item', item: { category: 'settings' } })
        expect(logic.values.highlightedKey).toBe(revealed.key)
    })

    it('scrolls back to a setting when its result is opened on the page that already shows it', () => {
        router.actions.push('/settings/project-customization#base-currency')
        const heading = document.createElement('h2')
        heading.id = 'base-currency'
        heading.scrollIntoView = jest.fn()
        document.body.appendChild(heading)

        logic.actions.activateRow(
            {
                kind: 'item',
                key: 'group-settings/settings-project-customization-base-currency',
                section: 'settings',
                item: {
                    id: 'settings-project-customization-base-currency',
                    name: 'Base currency',
                    category: 'settings',
                    href: '/settings/project-customization#base-currency',
                },
            },
            false,
            'enter'
        )

        expect(heading.scrollIntoView).toHaveBeenCalled()
        heading.remove()
    })
})
