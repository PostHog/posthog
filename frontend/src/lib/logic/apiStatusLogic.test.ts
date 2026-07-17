import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { CONNECTION_ISSUE_PERSISTENCE_MS, apiStatusLogic } from './apiStatusLogic'

const MOCK_IMPERSONATED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_impersonated: true,
    is_impersonated_read_only: true,
    is_impersonated_until: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
    },
}

describe('apiStatusLogic', () => {
    let logic: ReturnType<typeof apiStatusLogic.build>

    describe('401 handling during impersonation', () => {
        it('skips auto-logout on 401 for impersonated users', async () => {
            useMocks({
                get: {
                    '/api/users/@me/': () => [401, {}],
                },
            })
            initKeaTests()
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)

            logic = apiStatusLogic()
            logic.mount()

            const logoutSpy = jest.spyOn(userLogic.actions, 'logout')

            const mockResponse = { status: 401, ok: false } as Response

            await expectLogic(logic, () => {
                logic.actions.onApiResponse(mockResponse)
            }).toFinishAllListeners()

            expect(logoutSpy).not.toHaveBeenCalled()
            logoutSpy.mockRestore()
        })

        it('triggers auto-logout on 401 for non-impersonated users', async () => {
            // The real logout listener submits a <form>, which jsdom doesn't implement
            const submitSpy = jest.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation()
            useMocks({
                get: {
                    '/api/users/@me/': () => [401, {}],
                },
            })
            initKeaTests()
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

            logic = apiStatusLogic()
            logic.mount()

            const logoutSpy = jest.spyOn(userLogic.actions, 'logout')

            const mockResponse = { status: 401, ok: false } as Response

            await expectLogic(logic, () => {
                logic.actions.onApiResponse(mockResponse)
            }).toFinishAllListeners()

            expect(logoutSpy).toHaveBeenCalled()
            logoutSpy.mockRestore()
            submitSpy.mockRestore()
        })
    })

    describe('internet connection issue detection', () => {
        it('flags only persistent failures as a toast and clears on the next success', async () => {
            // Without common logics: their boot API calls succeed against the default
            // mocks and dispatch stray ok responses that reset the failure window
            initKeaTests(false)
            logic = apiStatusLogic()
            logic.mount()

            const nowSpy = jest.spyOn(Date, 'now')
            const errorSpy = jest.spyOn(lemonToast, 'error').mockReturnValue('toast-id')
            const dismissSpy = jest.spyOn(lemonToast, 'dismiss').mockImplementation(() => {})
            const failedFetch = (): void => logic.actions.onApiResponse(undefined, new Error('Failed to fetch'))

            try {
                // A single transient failure (e.g. during app boot) must not flag
                nowSpy.mockReturnValue(1_000)
                await expectLogic(logic, failedFetch).toFinishAllListeners()
                expect(logic.values.internetConnectionIssue).toBe(false)

                // Repeated failures within the persistence window still don't flag
                nowSpy.mockReturnValue(2_000)
                await expectLogic(logic, failedFetch).toFinishAllListeners()
                expect(logic.values.internetConnectionIssue).toBe(false)

                // Failures persisting past the window flag, as a toast (never an in-flow banner)
                nowSpy.mockReturnValue(1_000 + CONNECTION_ISSUE_PERSISTENCE_MS)
                await expectLogic(logic, failedFetch).toFinishAllListeners()
                expect(logic.values.internetConnectionIssue).toBe(true)
                expect(errorSpy).toHaveBeenCalledWith(
                    expect.stringContaining('trouble connecting'),
                    expect.objectContaining({ toastId: 'internet-connection-issue' })
                )

                // A successful response clears the flag, dismisses the toast, and resets
                // the window — the next lone failure doesn't flag again
                await expectLogic(logic, () =>
                    logic.actions.onApiResponse({ status: 200, ok: true } as Response)
                ).toFinishAllListeners()
                expect(logic.values.internetConnectionIssue).toBe(false)
                expect(dismissSpy).toHaveBeenCalledWith('internet-connection-issue')

                nowSpy.mockReturnValue(60_000)
                await expectLogic(logic, failedFetch).toFinishAllListeners()
                expect(logic.values.internetConnectionIssue).toBe(false)
            } finally {
                nowSpy.mockRestore()
                errorSpy.mockRestore()
                dismissSpy.mockRestore()
            }
        })
    })

    describe('read-only impersonation 403 handling', () => {
        const READ_ONLY_DETAIL = 'This action is not allowed during read-only user impersonation.'

        it('surfaces the block reason as a toast', async () => {
            initKeaTests()
            logic = apiStatusLogic()
            logic.mount()

            const errorSpy = jest.spyOn(lemonToast, 'error').mockReturnValue('toast-id')
            const mockResponse = {
                status: 403,
                ok: false,
                json: () => Promise.resolve({ code: 'impersonation_read_only', detail: READ_ONLY_DETAIL }),
            } as unknown as Response

            await expectLogic(logic, () => {
                logic.actions.onApiResponse(mockResponse)
            }).toFinishAllListeners()

            expect(errorSpy).toHaveBeenCalledWith(READ_ONLY_DETAIL, { hideButton: true })
            errorSpy.mockRestore()
        })

        it('does not toast for unrelated 403s', async () => {
            initKeaTests()
            logic = apiStatusLogic()
            logic.mount()

            const errorSpy = jest.spyOn(lemonToast, 'error').mockReturnValue('toast-id')
            const mockResponse = {
                status: 403,
                ok: false,
                json: () => Promise.resolve({ code: 'permission_denied', detail: 'Nope' }),
            } as unknown as Response

            await expectLogic(logic, () => {
                logic.actions.onApiResponse(mockResponse)
            }).toFinishAllListeners()

            expect(errorSpy).not.toHaveBeenCalled()
            errorSpy.mockRestore()
        })
    })
})
