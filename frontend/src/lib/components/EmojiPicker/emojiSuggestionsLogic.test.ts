import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'

import * as api from '~/generated/core/api'
import { initKeaTests } from '~/test/init'

import { emojiSuggestionsLogic } from './emojiSuggestionsLogic'

jest.mock('~/generated/core/api', () => ({ emojiSearchSuggestRetrieve: jest.fn() }))

describe('emojiSuggestionsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 1, name: 'Test project' } as any)
        jest.mocked(api.emojiSearchSuggestRetrieve).mockReset()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('only requests suggestions for the last query typed in a burst', async () => {
        jest.useFakeTimers()
        jest.mocked(api.emojiSearchSuggestRetrieve).mockResolvedValue({ suggestions: [] })
        const logic = emojiSuggestionsLogic
        logic.mount()

        logic.actions.setQuery('qzx')
        await jest.advanceTimersByTimeAsync(100)
        logic.actions.setQuery('qzxy')
        await jest.advanceTimersByTimeAsync(100)
        logic.actions.setQuery('qzxyz')
        expect(logic.values.loading).toBe(true)
        await jest.advanceTimersByTimeAsync(200)

        expect(jest.mocked(api.emojiSearchSuggestRetrieve).mock.calls.map((call) => call[1].query)).toEqual(['qzxyz'])
        expect(logic.values.loading).toBe(false)
    })

    it('shows an earlier query from the cache without a new request', async () => {
        jest.mocked(api.emojiSearchSuggestRetrieve).mockImplementation(async (_, params) => ({
            suggestions: [{ emoji: params.query === 'jurassic' ? '🦖' : '🎢', label: params.query }],
        }))
        const logic = emojiSuggestionsLogic
        logic.mount()

        logic.actions.setQuery('jurassic')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setQuery('rides')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setQuery('jurassic')

        expect(logic.values.loading).toBe(false)
        expect(logic.values.suggestions).toEqual([{ emoji: '🦖', label: 'jurassic' }])
        expect(jest.mocked(api.emojiSearchSuggestRetrieve).mock.calls.map((call) => call[1].query)).toEqual([
            'jurassic',
            'rides',
        ])
    })
})
