import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
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

    describe('writes that need a fresh session', () => {
        const STALE_SESSION = { type: 'authentication_error', code: 'sensitive_action_required_reauth' }
        let patchCalls: number

        beforeEach(() => {
            patchCalls = 0
            useMocks({
                patch: {
                    '/api/users/@me/': () => (++patchCalls === 1 ? [403, STALE_SESSION] : [200, { saved: true }]),
                },
                post: {
                    '/api/personal_api_keys/': () => [403, STALE_SESSION],
                },
            })
            initKeaTests()
            logic = apiStatusLogic()
            logic.mount()
            timeSensitiveAuthenticationLogic.mount()
        })

        it.each([
            ['success', { value: { saved: true } }, 2],
            ['failure', { error: expect.objectContaining({ status: 403, code: STALE_SESSION.code }) }, 1],
        ] as const)(
            'on re-authentication %s, settles the write as %o after %i request(s)',
            async (outcome, expected, calls) => {
                const result = api.update('api/users/@me/', { notification_settings: {} }).then(
                    (value) => ({ value }),
                    (error) => ({ error })
                )
                await expectLogic(logic).toDispatchActions(['setTimeSensitiveAuthenticationRequired'])
                logic.actions.resolveSensitiveAction(outcome)

                expect(await result).toEqual(expected)
                expect(patchCalls).toBe(calls)
            }
        )

        it('settles every write waiting on the same re-authentication', async () => {
            const first = api.update('api/users/@me/', { theme_mode: 'dark' }).catch(() => 'first settled')
            const second = api.create('api/personal_api_keys/', {}).catch(() => 'second settled')
            await expectLogic(logic).toDispatchActions([
                'setTimeSensitiveAuthenticationRequired',
                'setTimeSensitiveAuthenticationRequired',
            ])
            logic.actions.resolveSensitiveAction('failure')

            expect(await Promise.all([first, second])).toEqual(['first settled', 'second settled'])
        })

        it('keeps the write waiting after a wrong password', async () => {
            const result = api.update('api/users/@me/', { notification_settings: {} })
            await expectLogic(logic).toDispatchActions(['setTimeSensitiveAuthenticationRequired'])

            timeSensitiveAuthenticationLogic.actions.submitReauthenticationFailure(new Error('Wrong password'), {})
            expect(patchCalls).toBe(1)
            logic.actions.resolveSensitiveAction('success')

            expect(await result).toEqual({ saved: true })
        })
    })
})
