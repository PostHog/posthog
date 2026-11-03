import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { commandKSearchLogic } from './commandKSearchLogic'

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
    ])('a new query from %s drops the remembered highlight', (_, changeQuery) => {
        logic.actions.setChipsAndText([{ key: 'is', value: 'dashboard', label: 'Dashboard', negated: false }], 'rev', 3)
        logic.actions.setHighlightedKey('recents/dashboard:1')

        changeQuery()

        expect(logic.values.highlightedKey).toBeNull()
    })

    test.each([
        ['retries a query whose request failed', true, undefined],
        ['reuses a query whose request answered', false, []],
    ])('%s when it is searched again', (_, failed, cached) => {
        logic.actions.remoteLoaded('ada', { persons: [] }, failed)
        const remoteBefore = logic.values.remote

        logic.actions.requestsStarted({ persons: 'ada', objects: 'ada' })

        expect(logic.values.remote.persons.cache['ada']).toEqual(cached)
        expect(logic.values.remote === remoteBefore).toBe(!failed)
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
        ['test', [{ input: 'session replay', picks: { 'product-Session replay': 1 } }]],
        ['control', []],
    ])('opening a ranked result in the %s group of unified ranking records the pick', (variant, expected) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.COMMAND_K_UNIFIED_RANKING]: variant })
        logic.actions.inputChanged('session replay', 14, false)

        logic.actions.activateRow(
            {
                kind: 'item',
                key: 'flat/product-Session replay',
                item: {
                    id: 'product-Session replay',
                    name: 'Session replay',
                    category: 'products',
                    onSelect: () => {},
                },
                section: 'products',
                highlightWords: ['session', 'replay'],
                ranked: true,
            },
            false,
            'click'
        )

        expect(logic.values.pickMemory).toEqual(expected.map((entry) => expect.objectContaining(entry)))
    })

    it('records a pick against the search whose rows are on screen', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.COMMAND_K_UNIFIED_RANKING]: 'test' })
        logic.actions.showQuery({
            remoteQueries: { results: 'replay' },
            localQuery: 'replay',
            themeItem: null,
            askAiQuestion: null,
            viewAll: null,
        })
        logic.actions.inputChanged('replay vision', 13, false)

        logic.actions.activateRow(
            {
                kind: 'item',
                key: 'best-matches/product-Session replay',
                item: {
                    id: 'product-Session replay',
                    name: 'Session replay',
                    category: 'products',
                    onSelect: () => {},
                },
                section: 'products',
                highlightWords: ['replay'],
                ranked: true,
            },
            false,
            'click'
        )

        expect(logic.values.pickMemory).toEqual([expect.objectContaining({ input: 'replay' })])
    })

    it('searches a keyboard layout correction until the text changes', () => {
        logic.actions.inputChanged('фзш', 3, false)
        logic.actions.correctLayout({ from: 'фзш', to: 'api' })

        expect(logic.values.localQuery).toEqual('api')
        expect(logic.values.requestQueries.objects).toEqual('api')

        logic.actions.inputChanged('фзшы', 4, false)

        expect(logic.values.localQuery).toEqual('фзшы')
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
})
