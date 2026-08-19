import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { NetworkError } from 'lib/api-error'
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

    describe('timeout handling', () => {
        it('shows the timeout toast even when another response arrives during the debounce window', async () => {
            initKeaTests()
            logic = apiStatusLogic()
            logic.mount()

            const errorSpy = jest.spyOn(lemonToast, 'error').mockReturnValue('toast-id')

            // A concurrent response in the same tick would cancel a debounced run at breakpoint(50).
            // The timeout toast must survive that, so it is dispatched alongside a successful response.
            await expectLogic(logic, () => {
                logic.actions.onApiResponse(undefined, new NetworkError('timeout'))
                logic.actions.onApiResponse({ status: 200, ok: true } as Response)
            }).toFinishAllListeners()

            expect(errorSpy).toHaveBeenCalledTimes(1)
            errorSpy.mockRestore()
        })
    })
})
