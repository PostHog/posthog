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

    describe('internet connection issue', () => {
        const failure = { message: 'Failed to fetch' }

        beforeEach(() => {
            jest.useFakeTimers()
            initKeaTests()
            logic = apiStatusLogic()
            logic.mount()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        // Each failure passes through a breakpoint(50) debounce, so advance past it to record.
        async function reportFailure(): Promise<void> {
            logic.actions.onApiResponse(undefined, failure)
            await jest.advanceTimersByTimeAsync(100)
        }

        // Report failures until the warning appears; return how many events it took.
        async function reportFailuresUntilWarned(max = 10): Promise<number> {
            let events = 0
            while (!logic.values.internetConnectionIssue && events < max) {
                await reportFailure()
                events++
            }
            return events
        }

        it('does not warn on a single failed fetch', async () => {
            await reportFailure()
            expect(logic.values.internetConnectionIssue).toBe(false)
        })

        it('warns only after several failures cluster together', async () => {
            const events = await reportFailuresUntilWarned()
            expect(logic.values.internetConnectionIssue).toBe(true)
            expect(events).toBeGreaterThanOrEqual(3)
        })

        it('clears the warning on the next successful response', async () => {
            await reportFailuresUntilWarned()
            expect(logic.values.internetConnectionIssue).toBe(true)

            logic.actions.onApiResponse({ status: 200, ok: true } as Response)
            await jest.advanceTimersByTimeAsync(1)
            expect(logic.values.internetConnectionIssue).toBe(false)
        })

        it('clears itself if no successful response arrives', async () => {
            logic.actions.setInternetConnectionIssue(true)
            expect(logic.values.internetConnectionIssue).toBe(true)

            await jest.advanceTimersByTimeAsync(30_000)
            expect(logic.values.internetConnectionIssue).toBe(false)
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
