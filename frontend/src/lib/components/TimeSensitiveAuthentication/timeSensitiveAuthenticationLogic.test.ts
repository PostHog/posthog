import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { ERROR_MESSAGES } from 'scenes/authentication/shared/loginErrorMessages'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { timeSensitiveAuthenticationLogic } from './timeSensitiveAuthenticationLogic'

jest.mock('lib/api')
jest.mock('posthog-js')

describe('timeSensitiveAuthenticationLogic', () => {
    let logic: ReturnType<typeof timeSensitiveAuthenticationLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockImplementation(() => null as any)
        logic = timeSensitiveAuthenticationLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    describe('initial state', () => {
        it('should have correct default values', async () => {
            await expectLogic(logic).toMatchValues({
                dismissedReauthentication: false,
                twoFactorRequired: false,
                precheckResponse: null,
            })
        })
    })

    describe('reauthentication form', () => {
        it('should validate password is required', async () => {
            await expectLogic(logic, () => {
                logic.actions.setReauthenticationValues({ password: '', token: undefined })
                logic.actions.submitReauthentication()
            }).toMatchValues({
                reauthenticationValidationErrors: {
                    password: 'Please enter your password to continue',
                },
            })
        })

        it('should validate 2FA token is required when 2FA is required', async () => {
            await expectLogic(logic, () => {
                logic.actions.setRequiresTwoFactor(true)
                logic.actions.setReauthenticationValues({ password: 'test', token: undefined })
                logic.actions.submitReauthentication()
            }).toMatchValues({
                reauthenticationValidationErrors: {
                    token: 'Please enter your 2FA code',
                },
            })
        })

        it('should handle successful reauthentication', async () => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

            await expectLogic(logic, () => {
                logic.actions.setReauthenticationValues({ password: 'test', token: undefined })
                logic.actions.submitReauthentication()
            })
                .toDispatchActions(['submitReauthentication'])
                .toMatchValues({
                    reauthenticationValidationErrors: {},
                })
        })
    })

    describe('session expiry', () => {
        it('should show authentication modal when session is expired', async () => {
            const mockUser = {
                ...MOCK_DEFAULT_USER,
                sensitive_session_expires_at: dayjs().subtract(1, 'hour').toISOString(),
            }
            userLogic.actions.loadUserSuccess(mockUser)

            await expectLogic(logic, () => {
                logic.actions.checkReauthentication()
            }).toMatchValues({
                showAuthenticationModal: true,
            })
        })

        it('should show authentication modal when session is about to expire', async () => {
            const mockUser = {
                ...MOCK_DEFAULT_USER,
                sensitive_session_expires_at: dayjs().add(4, 'minutes').toISOString(),
            }
            userLogic.actions.loadUserSuccess(mockUser)

            await expectLogic(logic, () => {
                logic.actions.checkReauthentication()
            }).toMatchValues({
                showAuthenticationModal: true,
            })
        })

        it('should not show authentication modal when session is not about to expire', async () => {
            const mockUser = {
                ...MOCK_DEFAULT_USER,
                sensitive_session_expires_at: dayjs().add(6, 'minutes').toISOString(),
            }
            userLogic.actions.loadUserSuccess(mockUser)

            await expectLogic(logic, () => {
                logic.actions.checkReauthentication()
            }).toMatchValues({
                showAuthenticationModal: false,
            })
        })
    })

    describe('modal interactions', () => {
        it('should handle modal dismissal', async () => {
            await expectLogic(logic, () => {
                logic.actions.setDismissedReauthentication(true)
            }).toMatchValues({
                dismissedReauthentication: true,
            })
        })

        it('should show modal when required', async () => {
            await expectLogic(logic, () => {
                apiStatusLogic.actions.setTimeSensitiveAuthenticationRequired(true)
            }).toMatchValues({
                showAuthenticationModal: true,
            })
        })

        it('should settle a pending checkReauthentication when the modal is dismissed', async () => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                sensitive_session_expires_at: dayjs().add(4, 'minutes').toISOString(),
            })

            const pending = logic.asyncActions.checkReauthentication()
            expect(logic.values.showAuthenticationModal).toBe(true) // guard: the check is actually pending on the modal
            logic.actions.setDismissedReauthentication(true)

            // Rejects (TypeError on undefined.message in kea's listener wrapper) if dismissal
            // rejects the stored callback pair instead of resolving it
            await pending

            await expectLogic(logic).toMatchValues({ showAuthenticationModal: false })
        })
    })

    describe('failed SSO re-authentication', () => {
        it('should report the error the backend sent back and drop it from the URL', async () => {
            router.actions.push('/settings/user', { error_code: 'reauth_user_mismatch' })

            logic.actions.showSsoReauthenticationError()

            expect(lemonToast.error).toHaveBeenCalledWith(ERROR_MESSAGES.reauth_user_mismatch)
            expect(router.values.searchParams).toEqual({})
        })

        it('should leave unrelated query params alone', async () => {
            router.actions.push('/settings/user', { tab: 'danger-zone' })

            logic.actions.showSsoReauthenticationError()

            expect(lemonToast.error).not.toHaveBeenCalled()
            expect(router.values.searchParams).toEqual({ tab: 'danger-zone' })
        })
    })
})
