import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { timeSensitiveAuthenticationLogic } from './timeSensitiveAuthenticationLogic'

jest.mock('lib/api')
jest.mock('posthog-js')

describe('timeSensitiveAuthenticationLogic', () => {
    let logic: ReturnType<typeof timeSensitiveAuthenticationLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = timeSensitiveAuthenticationLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
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

        it('should show authentication modal when a step-up is required (no expiry window)', async () => {
            // The backend reports `sensitive_session_expires_at: null` while a risk-based step-up
            // is pending. A time-only check would treat that as "no reason to re-auth" and let the
            // action fall through to a 403 — the regression this guards against.
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                sensitive_session_expires_at: null,
            })

            await expectLogic(logic, () => {
                logic.actions.checkReauthentication()
            }).toMatchValues({
                showAuthenticationModal: true,
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

        it('should resolve a pending checkReauthentication with false when the modal is dismissed', async () => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                sensitive_session_expires_at: dayjs().add(4, 'minutes').toISOString(),
            })

            const pending = logic.asyncActions.checkReauthentication()
            expect(logic.values.showAuthenticationModal).toBe(true) // guard: the check is actually pending on the modal
            logic.actions.setDismissedReauthentication(true)

            // Must resolve `false` (not reject, not resolve truthy): callers key off this to abort
            // the blocked action instead of re-firing it into the same 403. A regression here brings
            // back the "re-authenticate, still blocked" loop.
            await expect(pending).resolves.toBe(false)

            await expectLogic(logic).toMatchValues({ showAuthenticationModal: false })
        })
    })
})
