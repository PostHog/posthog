import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { hogInvocationsLogic } from './hogInvocationsLogic'

describe('hogInvocationsLogic', () => {
    let logic: ReturnType<typeof hogInvocationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = hogInvocationsLogic({ id: 'fn-1', functionKind: 'hog_function' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('fails soft and flags an errored state when the sparkline query 500s', async () => {
        // A server error on the secondary sparkline query must not bubble up as an
        // unhandled rejection / captured exception — the loader resolves (Success),
        // sets the errored flag, and keeps the previous (null) data.
        useMocks({
            post: {
                '/api/environments/:team/query/:kind': () => [500, { detail: 'A server error occurred.' }],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadSparkline(null)
        })
            .toDispatchActions(['loadSparkline', 'setSparklineErrored', 'loadSparklineSuccess'])
            .toNotHaveDispatchedActions(['loadSparklineFailure'])
            .toMatchValues({
                sparklineErrored: true,
                sparkline: null,
            })
    })

    it('clears the errored flag once a later sparkline query succeeds', async () => {
        let calls = 0
        useMocks({
            post: {
                '/api/environments/:team/query/:kind': () => {
                    calls += 1
                    return calls === 1 ? [500, { detail: 'A server error occurred.' }] : [200, { results: [] }]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadSparkline(null)
        })
            .toDispatchActions(['setSparklineErrored', 'loadSparklineSuccess'])
            .toMatchValues({ sparklineErrored: true })

        await expectLogic(logic, () => {
            logic.actions.loadSparkline(null)
        })
            .toDispatchActions(['loadSparklineSuccess'])
            .toMatchValues({ sparklineErrored: false })
    })
})
