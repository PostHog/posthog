import { expectLogic } from 'kea-test-utils'
import { MOCK_DEFAULT_USER } from 'lib/api.mock'
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
    })
})
