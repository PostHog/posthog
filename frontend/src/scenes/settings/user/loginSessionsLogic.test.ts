import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { loginSessionsLogic } from './loginSessionsLogic'

const CURRENT_ID = '0190a1b2-0000-7000-8000-000000000001'
const OTHER_ID = '0190a1b2-0000-7000-8000-000000000002'

const SESSIONS = [
    {
        id: CURRENT_ID,
        last_activity: '2026-06-18T00:00:00Z',
        location: 'San Francisco, United States',
        device: 'Chrome 135 on macOS',
        login_method: 'password',
        is_current: true,
    },
    {
        id: OTHER_ID,
        last_activity: '2026-06-10T00:00:00Z',
        location: 'London, United Kingdom',
        device: 'Firefox 120 on Windows',
        login_method: 'Google',
        is_current: false,
    },
]

describe('loginSessionsLogic', () => {
    let logic: ReturnType<typeof loginSessionsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/users/@me/login_sessions/': () => [200, SESSIONS],
            },
            delete: {
                '/api/users/@me/login_sessions/:id/': () => [204, null],
            },
            post: {
                '/api/users/@me/login_sessions/revoke_others/': () => [200, { revoked_count: 1 }],
            },
        })
        initKeaTests()
        logic = loginSessionsLogic()
        logic.mount()
    })

    it('loads login sessions on mount', async () => {
        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            loginSessions: SESSIONS,
        })
    })

    it('removes a session from the list when revoked', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.revokeSession(OTHER_ID)

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                loginSessions: [SESSIONS[0]],
            })
    })

    it('keeps only the current session when revoking others', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.revokeOtherSessions()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                loginSessions: [SESSIONS[0]],
            })
    })
})
