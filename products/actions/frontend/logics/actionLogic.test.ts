import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { actionLogic } from './actionLogic'

describe('actionLogic', () => {
    let logic: ReturnType<typeof actionLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    // A deleted or cross-project action must render the not-found scene, not spin forever. Guard the
    // 404 -> actionMissing path, and that other failures stay errors rather than a silent not-found.
    it.each([
        { status: 404, expectedMissing: true },
        { status: 500, expectedMissing: false },
    ])(
        'sets actionMissing=$expectedMissing when loadAction fails with $status',
        async ({ status, expectedMissing }) => {
            useMocks({
                get: {
                    '/api/projects/:team/actions/:id/': () => [status, { detail: 'Not found.' }],
                },
            })
            initKeaTests()
            logic = actionLogic({ id: 42 })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadActionFailure'])
            expect(logic.values.actionMissing).toBe(expectedMissing)
        }
    )
})
