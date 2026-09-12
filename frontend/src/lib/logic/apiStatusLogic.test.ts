import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { apiStatusLogic } from './apiStatusLogic'

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

    describe('connection warning', () => {
        // The kea test plugin collapses listener breakpoints, so the recovery timer fires at once
        // here. Assert on the actions rather than on the settled value.
        const issueSetTo =
            (issue: boolean) =>
            (action: Record<string, any>): boolean =>
                action.type === logic.actionTypes.setInternetConnectionIssue && action.payload.issue === issue

        beforeEach(() => {
            // Without common logic: preflight's own request answers mid-test and its onApiResponse
            // cancels the listener under test.
            initKeaTests(false)
            logic = apiStatusLogic()
            logic.mount()
        })

        // WebKit and Gecko word an unreachable server differently from Chromium, so a match on
        // Chromium's wording alone leaves Safari and Firefox with no warning at all.
        it.each([['Failed to fetch'], ['Load failed'], ['NetworkError when attempting to fetch resource.']])(
            'raises the warning for "%s"',
            async (message) => {
                await expectLogic(logic, () => {
                    logic.actions.onApiResponse(undefined, new TypeError(message))
                }).toDispatchActions([issueSetTo(true)])
            }
        )

        it('ignores a status-less failure that is not a fetch failure', async () => {
            await expectLogic(logic, () => {
                logic.actions.onApiResponse(undefined, new TypeError('x is not a function'))
            }).toFinishAllListeners()

            expect(logic.values.internetConnectionIssue).toBe(false)
        })

        // The request the edge drops fails with the same message as an unreachable server, and it
        // is what the false warning was built on.
        it('stays quiet for a request that ran too long', async () => {
            await expectLogic(logic, () => {
                logic.actions.onApiResponse(undefined, new TypeError('Failed to fetch'), 104000)
            }).toFinishAllListeners()

            expect(logic.values.internetConnectionIssue).toBe(false)
        })

        // A scene that runs one request has no later response to clear the warning with, so
        // without the timer it stays up for the rest of the session.
        it('clears itself when no later response reports back', async () => {
            await expectLogic(logic, () => {
                logic.actions.onApiResponse(undefined, new TypeError('Failed to fetch'))
            }).toDispatchActions([issueSetTo(true), issueSetTo(false)])
        })
    })

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
