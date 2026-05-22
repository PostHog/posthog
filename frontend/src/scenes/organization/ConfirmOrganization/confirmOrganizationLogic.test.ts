import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

describe('confirmOrganizationLogic', () => {
    let logic: ReturnType<typeof confirmOrganizationLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
                '/api/signup/resend-invite': () => [200, { sent: true }],
            },
        })
        initKeaTests()
        logic = confirmOrganizationLogic()
        logic.mount()
    })

    describe('query params', () => {
        it('set the default values', async () => {
            router.actions.push('/organization/confirm-creation', {
                email: 'spike@spike.com',
                first_name: 'Spike',
                organization_name: 'Spikes Inc',
                role_at_organization: 'engineering',
            })

            expectLogic(logic)
                .toDispatchActions(['setEmail', 'setConfirmOrganizationValues'])
                .toMatchValues({
                    confirmOrganization: {
                        first_name: 'Spike',
                        organization_name: 'Spikes Inc',
                        role_at_organization: 'engineering',
                    },
                    email: 'spike@spike.com',
                })
        })
    })

    describe('form', () => {
        it('requires org name and first name to be set', async () => {
            await expectLogic(logic, () => {
                logic.actions.submitConfirmOrganization()
            }).toMatchValues({
                confirmOrganizationValidationErrors: {
                    first_name: 'Please enter your name',
                    organization_name: 'Please enter your organization name',
                },
            })
        })
    })

    describe('pending invite precheck', () => {
        it('surfaces a pending invite for the pre-filled email', async () => {
            useMocks({
                post: {
                    '/api/signup/precheck': () => [
                        200,
                        { email_exists: false, pending_invite: { organization_name: 'Acme Corp' } },
                    ],
                },
            })
            router.actions.push('/organization/confirm-creation', { email: 'alice@acme.com' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.pendingInvite).toEqual({ organization_name: 'Acme Corp' })
        })

        it('leaves pendingInvite null when no invite is returned', async () => {
            router.actions.push('/organization/confirm-creation', { email: 'stranger@nowhere.com' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.pendingInvite).toBeNull()
        })

        it('clears the pending invite when dismissed', async () => {
            logic.actions.setPendingInvite({ organization_name: 'Acme Corp' })
            logic.actions.dismissPendingInvite()
            expect(logic.values.pendingInvite).toBeNull()
        })

        it('does not call precheck when there is no email in the URL', async () => {
            router.actions.push('/organization/confirm-creation')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.pendingInvite).toBeNull()
        })
    })

    describe('resend invite', () => {
        it('marks the invite as resent after resendPendingInvite succeeds', async () => {
            logic.actions.setPendingInvite({ organization_name: 'Acme Corp' })
            logic.actions.resendPendingInvite('alice@acme.com')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.pendingInviteResent).toBe(true)
            expect(logic.values.isPendingInviteResending).toBe(false)
        })

        it('clears the resent state when a new invite is shown', async () => {
            logic.actions.setPendingInvite({ organization_name: 'Acme Corp' })
            logic.actions.setPendingInviteResent(true)
            logic.actions.setPendingInvite({ organization_name: 'Other Corp' })
            expect(logic.values.pendingInviteResent).toBe(false)
        })
    })

    describe('loginUrl', () => {
        it('returns /login when there is no next path', async () => {
            router.actions.push('/organization/confirm-creation')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.loginUrl).toBe('/login')
        })

        it('preserves a relative next path', async () => {
            router.actions.push('/organization/confirm-creation', { next: '/insights' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.loginUrl).toBe('/login?next=%2Finsights')
        })
    })
})
