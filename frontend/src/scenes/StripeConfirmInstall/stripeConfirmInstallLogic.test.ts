import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import apiReal from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { stripeConfirmInstallLogic } from './stripeConfirmInstallLogic'

describe('stripeConfirmInstallLogic', () => {
    let logic: ReturnType<typeof stripeConfirmInstallLogic.build>
    let createSpy: jest.SpyInstance

    useMocks({
        get: {
            '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
        },
    })

    beforeEach(() => {
        initKeaTests()
        logic = stripeConfirmInstallLogic()
        logic.mount()
        createSpy = jest.spyOn(apiReal.integrations, 'create').mockResolvedValue({
            id: 42,
            kind: 'stripe',
            display_name: 'acct_123',
            icon_url: '',
            config: {},
            created_at: '2026-04-26T00:00:00Z',
        } as any)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('urlToAction', () => {
        it('reads stripe install params from URL', async () => {
            router.actions.push(
                '/integrations/stripe/confirm-install?code=ac_123&stripe_user_id=acct_456&account_id=acc_789&user_id=usr_1'
            )
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.params).toEqual({
                code: 'ac_123',
                stripe_user_id: 'acct_456',
                account_id: 'acc_789',
                user_id: 'usr_1',
            })
            expect(logic.values.hasRequiredParams).toBe(true)
        })

        it('marks params as missing if code is absent', async () => {
            router.actions.push('/integrations/stripe/confirm-install?stripe_user_id=acct_456')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.hasRequiredParams).toBe(false)
        })
    })

    describe('confirmInstall', () => {
        beforeEach(async () => {
            router.actions.push(
                '/integrations/stripe/confirm-install?code=ac_123&stripe_user_id=acct_456&account_id=acc_789&user_id=usr_1'
            )
            await expectLogic(logic).toFinishAllListeners()
        })

        it('POSTs to integrations.create with stripe params and redirects on success', async () => {
            await expectLogic(logic, () => {
                logic.actions.confirmInstall()
            }).toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith({
                kind: 'stripe',
                config: {
                    code: 'ac_123',
                    stripe_user_id: 'acct_456',
                    account_id: 'acc_789',
                    user_id: 'usr_1',
                },
            })
            expect(router.values.location.pathname).toContain('/settings/project-integrations')
            expect(String(router.values.searchParams.integration_id)).toBe('42')
        })

        it('does not POST if required params are missing', async () => {
            router.actions.push('/integrations/stripe/confirm-install')
            await expectLogic(logic).toFinishAllListeners()
            createSpy.mockClear()

            await expectLogic(logic, () => {
                logic.actions.confirmInstall()
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
        })

        it('clears submitting state on API failure', async () => {
            createSpy.mockRejectedValueOnce(new Error('boom'))

            await expectLogic(logic, () => {
                logic.actions.confirmInstall()
            }).toFinishAllListeners()

            expect(logic.values.isSubmitting).toBe(false)
        })
    })

    describe('cancelInstall', () => {
        it('redirects to settings without calling the API', async () => {
            router.actions.push('/integrations/stripe/confirm-install?code=ac_123&stripe_user_id=acct_456')
            await expectLogic(logic).toFinishAllListeners()
            createSpy.mockClear()

            await expectLogic(logic, () => {
                logic.actions.cancelInstall()
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toContain('/settings/project-integrations')
        })
    })
})
