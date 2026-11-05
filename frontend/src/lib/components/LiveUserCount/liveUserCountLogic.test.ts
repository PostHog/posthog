import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { liveUserCountLogic } from './liveUserCountLogic'

describe('liveUserCountLogic', () => {
    const originalFetch = global.fetch

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [[5]] } as any)
        global.fetch = jest.fn().mockResolvedValue({ json: () => Promise.resolve({ users_on_product: 7 }) })
    })

    afterEach(() => {
        jest.useRealTimers()
        global.fetch = originalFetch
    })

    it('keeps polling the live stats endpoint after LIVESTREAM_HOGQL turns off while mounted', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LIVESTREAM_HOGQL], {
            [FEATURE_FLAGS.LIVESTREAM_HOGQL]: true,
        })
        const logic = liveUserCountLogic({ pollIntervalMs: 30000 })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.liveUserCount).toBe(5)

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.LIVESTREAM_HOGQL]: false })
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.liveUserCount).toBe(7)

        jest.mocked(global.fetch).mockClear()
        await jest.advanceTimersByTimeAsync(60000)
        expect(global.fetch).toHaveBeenCalledTimes(2)
    })
})
