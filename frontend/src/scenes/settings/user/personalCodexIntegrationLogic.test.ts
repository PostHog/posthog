import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

const AUTH_FILE = JSON.stringify({
    tokens: { access_token: 'fake-access', refresh_token: 'fake-refresh', id_token: 'fake-id' },
})
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
    let connectRequests: number
    let pendingRead: ReturnType<typeof deferred<void>> | null

    beforeEach(() => {
        connectRequests = 0
        pendingRead = null
        useMocks({
            get: {
                '/api/users/@me/integrations/codex/': async () => {
                    await pendingRead?.promise
                    return [200, NOT_CONNECTED]
                },
            },
            post: {
                '/api/users/@me/integrations/codex/': () => {
                    connectRequests += 1
                    return [200, CONNECTED]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('does not connect when the dialog closes before the clipboard read finishes', async () => {
        const clipboard = deferred<string>()
        Object.assign(navigator, { clipboard: { readText: () => clipboard.promise, writeText: jest.fn() } })
        logic = personalCodexIntegrationLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openConnectModal('settings')
        logic.actions.pasteFromClipboard()
        logic.actions.closeConnectModal()
        clipboard.resolve(AUTH_FILE)
        await expectLogic(logic).toFinishAllListeners()

        expect(connectRequests).toBe(0)
        expect(logic.values.authFileText).toBe('')
    })

    it('connects once when two clipboard reads land together', async () => {
        const clipboard = deferred<string>()
        Object.assign(navigator, { clipboard: { readText: () => clipboard.promise, writeText: jest.fn() } })
        logic = personalCodexIntegrationLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openConnectModal('settings')
        logic.actions.pasteFromClipboard()
        logic.actions.pasteFromClipboard()
        clipboard.resolve(AUTH_FILE)
        await expectLogic(logic).toDispatchActions(['connectCodexSuccess']).toFinishAllListeners()

        expect(connectRequests).toBe(1)
    })

    it('drops an invalid paste so the dialog does not show it as received', async () => {
        logic = personalCodexIntegrationLogic()
        logic.mount()
        logic.actions.openConnectModal('settings')

        logic.actions.pasteAuthFile('codex login --device-auth')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.authFileText).toBe('')
        expect(logic.values.connectError).toContain('does not hold a Codex sign-in')
        expect(connectRequests).toBe(0)
    })

    it('keeps a new connection when an older reload finishes after it', async () => {
        pendingRead = deferred<void>()
        logic = personalCodexIntegrationLogic()
        logic.mount()

        logic.actions.openConnectModal('settings')
        logic.actions.pasteAuthFile(AUTH_FILE)
        await expectLogic(logic, () => undefined).toDispatchActions(['connectCodexSuccess'])
        pendingRead.resolve()
        await expectLogic(logic).toFinishAllListeners()

        expect(connectRequests).toBe(1)
        expect(logic.values.codexIntegration?.status).toBe('connected')
    })
})
