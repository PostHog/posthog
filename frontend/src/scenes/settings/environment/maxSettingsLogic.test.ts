import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CORE_MEMORY_MAX_CHARACTERS, maxSettingsLogic } from './maxSettingsLogic'

describe('maxSettingsLogic', () => {
    afterEach(resumeKeaLoadersErrors)
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
        'surfaces a load error instead of masquerading as empty memory when the load responds with %s',
        async (status) => {
            silenceKeaLoadersErrors()
            useMocks({
                get: {
                    '/api/environments/:team_id/core_memory/': () => [status, { detail: 'nope' }],
                },
            })
            logic = maxSettingsLogic()
            logic.mount()

            // A failed load must not read as empty memory: it dispatches a failure and populates the
            // error state so the UI can show a retry, not a blank editable textarea.
            await expectLogic(logic)
                .toDispatchActions(['loadCoreMemoryFailure'])
                .toMatchValues({ coreMemory: null, isLoading: false })
            expect(logic.values.coreMemoryLoadError).toBeTruthy()
        }
    )

    it('flags text over the character limit as over the limit', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/core_memory/': () => [
                    200,
                    { results: [{ id: 'mem-1', text: 'x'.repeat(15546) }] },
                ],
            },
        })
        logic = maxSettingsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadCoreMemorySuccess', 'setCoreMemoryFormValue'])
        expect(logic.values.coreMemoryOverLimit).toBe(true)

        logic.actions.trimCoreMemoryToFit()
        expect(logic.values.coreMemoryForm.text).toHaveLength(10000)
        expect(logic.values.coreMemoryOverLimit).toBe(false)
    })

    // A saved memory at or near the cap makes the agent's own appends fail, and that failure never
    // reaches the user in chat, so settings has to show it.
    it.each([
        ['at the cap', CORE_MEMORY_MAX_CHARACTERS, 0, true],
        ['just under the cap', CORE_MEMORY_MAX_CHARACTERS - 100, 100, true],
        ['with room to spare', 100, CORE_MEMORY_MAX_CHARACTERS - 100, false],
    ])('reports the space left on a saved memory %s', async (_label, savedLength, spaceLeft, lowOnSpace) => {
        useMocks({
            get: {
                '/api/environments/:team_id/core_memory/': () => [
                    200,
                    { results: [{ id: 'mem-1', text: 'x'.repeat(savedLength as number) }] },
                ],
            },
        })
        logic = maxSettingsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadCoreMemorySuccess'])
        expect(logic.values.coreMemorySpaceLeft).toBe(spaceLeft)
        expect(logic.values.coreMemoryLowOnSpace).toBe(lowOnSpace)
    })
})
