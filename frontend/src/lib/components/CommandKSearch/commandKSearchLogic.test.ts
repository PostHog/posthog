import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
        ['answered with nothing', false, { from: 'zzq_xyw', to: 'zzq xyw' }],
        ['answered, but one failed', true, null],
    ])('corrects a search only after every source %s', (_, oneFailed, expected) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.COMMAND_K_UNIFIED_RANKING]: 'test' })
        logic.actions.inputChanged('zzq_xyw', 7, false)
        const sources = Object.keys(logic.values.remoteQueries)
        expect(sources.length).toBeGreaterThan(1)

        logic.actions.remoteLoaded('zzq_xyw', { results: [] })
        expect(logic.values.searchCorrection).toBeNull()

        sources.forEach((source, index) => {
            logic.actions.remoteLoaded(
                'zzq_xyw',
                { [source]: [] } as RemoteResults,
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
})
