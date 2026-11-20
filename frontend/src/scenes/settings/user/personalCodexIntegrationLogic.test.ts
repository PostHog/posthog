import { expectLogic } from 'kea-test-utils'

import type { UserCodexLoginRequestApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

const CONNECTED = { status: 'connected', email: 'jane@example.com', plan_type: 'pro' }
const NOT_CONNECTED = { status: 'not_connected' }

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((res) => {
        resolve = res
    })
    return { promise, resolve }
}

describe('personalCodexIntegrationLogic', () => {
    let logic: ReturnType<typeof personalCodexIntegrationLogic.build>
    let loginId: string
    let loginStatus: string
    let pendingStart: ReturnType<typeof deferred<void>> | null
    let canceled: string[]
    let submittedFields: string[]

    beforeEach(() => {
        loginStatus = 'pending'
        pendingStart = null
        canceled = []
        submittedFields = []
        useMocks({
            get: {
                '/api/users/@me/integrations/codex/': () => [
                    200,
                    loginStatus === 'connected' ? CONNECTED : NOT_CONNECTED,
                ],
                '/api/users/@me/integrations/codex/login/:id/': () => [
                    200,
                    {
                        login_id: loginId,
                        status: loginStatus,
                        user_code: loginStatus === 'pending' ? 'TEST-CODE' : null,
                    },
                ],
            },
            post: {
                '/api/users/@me/integrations/codex/login/': async ({ request }) => {
                    const body = (await request.json()) as UserCodexLoginRequestApi
                    loginId = body.login_id
                    submittedFields = Object.keys(body)
                    await pendingStart?.promise
                    return [200, { login_id: loginId, status: 'starting', user_code: null }]
                },
            },
            delete: {
                '/api/users/@me/integrations/codex/login/:id/': (req) => {
                    canceled.push(req.params.id as string)
                    return [204]
                },
                '/api/users/@me/integrations/codex/': () => [204],
            },
        })
        initKeaTests()
        logic = personalCodexIntegrationLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    })

    const setHidden = (hidden: boolean): void => {
        Object.defineProperty(document, 'hidden', { configurable: true, value: hidden })
        document.dispatchEvent(new Event('visibilitychange'))
    }

    it.each([false, true])('connects without uploading tokens after switching tabs: %s', async (switchTabs) => {
        await expectLogic(logic, () => logic.actions.openConnectModal('settings')).toFinishAllListeners()
        expect(submittedFields).toEqual(['login_id'])
        expect(logic.values.login?.user_code).toBe('TEST-CODE')
        expect(logic.values.connecting).toBe(true)
        if (switchTabs) {
            setHidden(true)
            setHidden(false)
        }
        loginStatus = 'connected'
        await expectLogic(logic, () => logic.actions.pollDeviceLogin()).toFinishAllListeners()
        expect(logic.values.codexIntegration).toEqual(CONNECTED)
        expect(logic.values.connectModalOpener).toBeNull()
        expect(logic.values.login).toBeNull()
        expect(canceled).toEqual([])
    })

    it.each(['expired', 'failed', 'canceled'])('shows a retry when the server reports %s', async (state) => {
        loginStatus = state
        await expectLogic(logic, () => logic.actions.openConnectModal('settings')).toFinishAllListeners()
        expect(logic.values.connectError).toContain('Try again')
        expect(logic.values.connecting).toBe(false)
        expect(logic.values.connectModalOpener).toBe('settings')
    })

    it.each([false, true])('handles a slow status request with a tab switch: %s', async (switchTabs) => {
        await expectLogic(logic, () => logic.actions.openConnectModal('settings')).toFinishAllListeners()
        const started = deferred<void>()
        const response = deferred<void>()
        let requests = 0
        loginStatus = 'connected'
        useMocks({
            get: {
                '/api/users/@me/integrations/codex/login/:id/': async () => {
                    const firstRequest = ++requests === 1
                    started.resolve()
                    await response.promise
                    return firstRequest ? [200, { login_id: loginId, status: 'connected', user_code: null }] : [503, {}]
                },
            },
        })
        logic.actions.pollDeviceLogin()
        await started.promise
        logic.actions.pollDeviceLogin()
        if (switchTabs) {
            setHidden(true)
        }
        response.resolve()
        await expectLogic(logic).toFinishAllListeners()
        if (switchTabs) {
            expect(logic.values.connectError).toBeNull()
            setHidden(false)
            useMocks({
                get: {
                    '/api/users/@me/integrations/codex/login/:id/': () => [
                        200,
                        { login_id: loginId, status: 'connected', user_code: null },
                    ],
                },
            })
            await expectLogic(logic, () => logic.actions.pollDeviceLogin()).toFinishAllListeners()
        }
        expect(logic.values.codexIntegration).toEqual(CONNECTED)
        expect(logic.values.connectModalOpener).toBeNull()
        expect(logic.values.connectError).toBeNull()
    })

    it.each(['login', 'account'])('recovers from a temporary %s failure on the same login attempt', async (read) => {
        await expectLogic(logic, () => logic.actions.openConnectModal('settings')).toFinishAllListeners()
        const originalLoginId = loginId
        let requests = 0
        loginStatus = 'connected'
        useMocks({
            get: {
                [read === 'login'
                    ? '/api/users/@me/integrations/codex/login/:id/'
                    : '/api/users/@me/integrations/codex/']: () =>
                    ++requests === 1
                        ? [503, {}]
                        : [
                              200,
                              read === 'login'
                                  ? { login_id: loginId, status: 'connected', user_code: null }
                                  : CONNECTED,
                          ],
            },
        })
        await expectLogic(logic, () => logic.actions.pollDeviceLogin()).toFinishAllListeners()
        expect(loginId).toBe(originalLoginId)
        expect(logic.values.codexIntegration).toEqual(CONNECTED)
        expect(logic.values.connectModalOpener).toBeNull()
        expect(logic.values.connectError).toBeNull()
    })

    it('cancels a login that starts after the dialog closes', async () => {
        pendingStart = deferred<void>()
        logic.actions.openConnectModal('settings')
        logic.actions.closeConnectModal()
        pendingStart.resolve()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.login).toBeNull()
        expect(logic.values.connectModalOpener).toBeNull()
        expect(canceled).toContain(loginId)
    })

    it.each([false, true])('cancels the active attempt and keeps a failed cancellation open: %s', async (fail) => {
        await expectLogic(logic, () => logic.actions.openConnectModal('settings')).toFinishAllListeners()
        if (fail) {
            useMocks({ delete: { '/api/users/@me/integrations/codex/login/:id/': () => [503, {}] } })
            await expectLogic(logic, () => logic.actions.closeConnectModal()).toFinishAllListeners()
            expect(logic.values.connectModalOpener).toBe('settings')
            expect(logic.values.login?.login_id).toBe(loginId)
            expect(logic.values.cancelError).toContain('Could not cancel')
            useMocks({
                delete: {
                    '/api/users/@me/integrations/codex/login/:id/': () => {
                        canceled.push(loginId)
                        return [204]
                    },
                },
            })
        }
        await expectLogic(logic, () => logic.actions.closeConnectModal()).toFinishAllListeners()
        expect(canceled).toEqual([loginId])
        expect(logic.values.login).toBeNull()
    })
})
