import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { maxSettingsLogic } from './maxSettingsLogic'

describe('maxSettingsLogic', () => {
    let logic: ReturnType<typeof maxSettingsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads core memory from the first result', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/core_memory/': () => [
                    200,
                    { results: [{ id: 'mem-1', text: 'remember this' }] },
                ],
            },
        })
        logic = maxSettingsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadCoreMemorySuccess'])
            .toMatchValues({ coreMemory: { id: 'mem-1', text: 'remember this' }, isLoading: false })
    })

    it.each([403, 408, 502, 504])(
        'falls back to null without throwing when the load responds with %s',
        async (status) => {
            useMocks({
                get: {
                    '/api/environments/:team_id/core_memory/': () => [status, { detail: 'nope' }],
                },
            })
            logic = maxSettingsLogic()
            logic.mount()

            // The loader catches non-OK responses so they resolve as success with a null value,
            // rather than bubbling up as an uncaught frontend error.
            await expectLogic(logic)
                .toDispatchActions(['loadCoreMemorySuccess'])
                .toNotHaveDispatchedActions(['loadCoreMemoryFailure'])
                .toMatchValues({ coreMemory: null, isLoading: false })
        }
    )

    it('falls back to null without throwing on a browser-level fetch failure', async () => {
        // `TypeError: Failed to fetch` (offline, aborted, or ad-blocked requests) is not an ApiError,
        // so a narrow `instanceof ApiError` catch would let it escape as an uncaught frontend error.
        // Core memory is optional UI state, so it must resolve as success with null instead.
        jest.spyOn(api.coreMemory, 'list').mockRejectedValueOnce(new TypeError('Failed to fetch'))
        logic = maxSettingsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadCoreMemorySuccess'])
            .toNotHaveDispatchedActions(['loadCoreMemoryFailure'])
            .toMatchValues({ coreMemory: null, isLoading: false })
    })
})
