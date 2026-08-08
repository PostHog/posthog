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

    describe('internet connection issue banner', () => {
        const networkError = { message: 'Failed to fetch' }
        const okResponse = { ok: true, status: 200 } as Response

        beforeEach(async () => {
            initKeaTests()
            logic = apiStatusLogic()
            logic.mount()
            // Let the listener finish attaching before dispatching the first response,
            // otherwise the initial synchronous dispatch is missed (a test-only artifact).
            await expectLogic(logic).toFinishAllListeners()
        })

        // A burst of failures within ~250ms coalesces into one strike, so each simulated
        // failure is spaced past that window to count as a separate strike.
        const failAndSettle = async (): Promise<void> => {
            await expectLogic(logic, () => {
                logic.actions.onApiResponse(undefined, networkError)
            })
                .delay(300)
                .toFinishAllListeners()
        }

        it('does not latch on a single transient network failure', async () => {
            await failAndSettle()

            expect(logic.values.internetConnectionIssue).toBe(false)
        })

        it('coalesces a simultaneous burst of failures into one strike', async () => {
            await expectLogic(logic, () => {
                logic.actions.onApiResponse(undefined, networkError)
                logic.actions.onApiResponse(undefined, networkError)
                logic.actions.onApiResponse(undefined, networkError)
            }).toFinishAllListeners()

            expect(logic.values.internetConnectionIssue).toBe(false)
        })

        it('latches only after repeated failures spaced over time', async () => {
            await failAndSettle()
            expect(logic.values.internetConnectionIssue).toBe(false)

            await failAndSettle()
            expect(logic.values.internetConnectionIssue).toBe(true)
        })

        it('a successful response resets the failure streak', async () => {
            await failAndSettle()

            await expectLogic(logic, () => {
                logic.actions.onApiResponse(okResponse)
            }).toFinishAllListeners()

            await failAndSettle()

            expect(logic.values.internetConnectionIssue).toBe(false)
        })

        it('clears itself after a timeout instead of staying stuck', () => {
            jest.useFakeTimers()
            try {
                logic.actions.setInternetConnectionIssue(true)
                expect(logic.values.internetConnectionIssue).toBe(true)

                jest.advanceTimersByTime(30_000)
                expect(logic.values.internetConnectionIssue).toBe(false)
            } finally {
                jest.useRealTimers()
            }
        })
    })
})
