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

    it('lets non-HTTP errors propagate so real regressions stay visible', async () => {
        // A programming error (not an ApiError) should surface as a failure, not be silently swallowed.
        jest.spyOn(api.coreMemory, 'list').mockRejectedValueOnce(new TypeError('boom'))
        logic = maxSettingsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadCoreMemoryFailure'])
            .toMatchValues({ coreMemory: null, isLoading: false })
    })
})
