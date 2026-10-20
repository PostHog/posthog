import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EMOJI_RELATED_SEARCH], {
            [FEATURE_FLAGS.EMOJI_RELATED_SEARCH]: true,
        })
        jest.mocked(api.emojiSearchSuggestRetrieve).mockReset()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        { flagEnabled: true, expectedQueries: ['qzxyz'] },
        { flagEnabled: false, expectedQueries: [] },
    ])(
        'with the flag enabled $flagEnabled, requests suggestions for $expectedQueries after a burst',
        async ({ flagEnabled, expectedQueries }) => {
            jest.useFakeTimers()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EMOJI_RELATED_SEARCH], {
                [FEATURE_FLAGS.EMOJI_RELATED_SEARCH]: flagEnabled,
            })
            jest.mocked(api.emojiSearchSuggestRetrieve).mockResolvedValue({ suggestions: [] })
            const logic = emojiSuggestionsLogic({ pickerKey: 'test' })
            logic.mount()

            logic.actions.setQuery('qzx')
            await jest.advanceTimersByTimeAsync(100)
            logic.actions.setQuery('qzxy')
            await jest.advanceTimersByTimeAsync(100)
            logic.actions.setQuery('qzxyz')
            expect(logic.values.loading).toBe(flagEnabled)
            await jest.advanceTimersByTimeAsync(200)

            expect(jest.mocked(api.emojiSearchSuggestRetrieve).mock.calls.map((call) => call[1].query)).toEqual(
                expectedQueries
            )
            expect(logic.values.loading).toBe(false)
        }
    )

    it.each(['jurassic', 'constructor'])(
        'shows an earlier query %s from the cache without a new request',
        async (firstQuery) => {
            jest.mocked(api.emojiSearchSuggestRetrieve).mockImplementation(async (_, params) => ({
                suggestions: [{ emoji: params.query === firstQuery ? '🦖' : '🎢', label: params.query }],
            }))
            const logic = emojiSuggestionsLogic({ pickerKey: 'test' })
            logic.mount()

            logic.actions.setQuery(firstQuery)
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setQuery('rides')
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setQuery(firstQuery)

            expect(logic.values.loading).toBe(false)
            expect(logic.values.suggestions).toEqual([{ emoji: '🦖', label: firstQuery }])
            expect(jest.mocked(api.emojiSearchSuggestRetrieve).mock.calls.map((call) => call[1].query)).toEqual([
                firstQuery,
                'rides',
            ])
        }
    )

    it('keeps the current failure when an earlier query fails later', async () => {
        jest.useFakeTimers()
        const rejectByQuery: Record<string, (error: Error) => void> = {}
        jest.mocked(api.emojiSearchSuggestRetrieve).mockImplementation(
            (_, params) => new Promise((_resolve, reject) => (rejectByQuery[params.query] = reject))
        )
        const logic = emojiSuggestionsLogic({ pickerKey: 'test' })
        logic.mount()

        logic.actions.setQuery('alpha')
        await jest.advanceTimersByTimeAsync(200)
        logic.actions.setQuery('bravo')
        await jest.advanceTimersByTimeAsync(200)
        rejectByQuery['bravo'](new Error('failed'))
        await jest.advanceTimersByTimeAsync(0)
        rejectByQuery['alpha'](new Error('failed'))
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.query).toBe('bravo')
        expect(logic.values.loading).toBe(false)
    })
})
