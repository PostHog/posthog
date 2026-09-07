import { expectLogic } from 'kea-test-utils'

import { loginLogic } from '~/exporter/ExporterLogin'
import { ExportType } from '~/exporter/types'
import { initKeaTests } from '~/test/init'

describe('loginLogic', () => {
    let logic: ReturnType<typeof loginLogic.build>
    let fetchMock: jest.Mock

    beforeEach(() => {
        initKeaTests(false)
        fetchMock = jest.fn()
        global.fetch = fetchMock as any
        logic = loginLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        document.documentElement.className = ''
    })

    /** Answer the password POST, then the token-authenticated GET that loads the unlocked share. */
    function mockUnlock(unlockedResponse: { ok: boolean; json: () => Promise<any> }): void {
        fetchMock.mockImplementation(async (_url: string, options: RequestInit = {}) => {
            if (options.method === 'POST') {
                return { status: 200, json: async () => ({ shareToken: 'jwt-token' }) }
            }
            if ((options.headers as Record<string, string>)?.Authorization) {
                return unlockedResponse
            }
            return { ok: true, status: 200, json: async () => ({}) }
        })
    }

    function unlockGetCall(): RequestInit {
        return fetchMock.mock.calls.find(
            ([, options]) => (options?.headers as Record<string, string>)?.Authorization
        )![1]
    }

    it('renders the unlocked share from the returned token instead of reloading', async () => {
        mockUnlock({ ok: true, json: async () => ({ type: ExportType.Embed, rootClassName: 'export-type-embed' }) })

        await expectLogic(logic, () => {
            logic.actions.setLoginValue('password', 'correct')
            logic.actions.submitLogin()
        }).toFinishAllListeners()

        expectLogic(logic).toMatchValues({
            unlockedData: { type: ExportType.Embed, rootClassName: 'export-type-embed', shareToken: 'jwt-token' },
            isSuccess: true,
        })

        // The share cookie is SameSite=Lax, so an embedded viewer can only authenticate with this header
        expect(unlockGetCall().headers).toMatchObject({
            Accept: 'application/json',
            Authorization: 'Bearer jwt-token',
        })
        expect(document.documentElement.classList.contains('export-type-embed')).toBe(true)
    })

    it('reports an error when the share does not load after the password is accepted', async () => {
        mockUnlock({ ok: true, json: async () => ({ type: ExportType.Unlock }) })

        await expectLogic(logic, () => {
            logic.actions.setLoginValue('password', 'correct')
            logic.actions.submitLogin()
        }).toFinishAllListeners()

        expectLogic(logic).toMatchValues({
            unlockedData: null,
            isSuccess: false,
            generalError: {
                code: 'unlock_failed',
                detail: 'Password accepted, but the content did not load. Try again.',
            },
        })
    })
})
