import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

describe('confirmOrganizationLogic', () => {
    let logic: ReturnType<typeof confirmOrganizationLogic.build>

    describe('with no pending invite', () => {
        beforeEach(() => {
            useMocks({
                post: {
                    '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
                },
            })
            initKeaTests()
            logic = confirmOrganizationLogic()
            logic.mount()
        })

        it('set the default values', async () => {
            router.actions.push('/organization/confirm-creation', {
                email: 'spike@spike.com',
                first_name: 'Spike',
                organization_name: 'Spikes Inc',
            })

            await expectLogic(logic)
                .toDispatchActions(['setConfirmOrganizationValues', 'setEmail'])
                .toMatchValues({
                    confirmOrganization: {
                        first_name: 'Spike',
                        organization_name: 'Spikes Inc',
                    },
                    email: 'spike@spike.com',
                })
        })

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

    describe('with a pending invite', () => {
        beforeEach(() => {
            useMocks({
                post: {
                    '/api/signup/precheck': () => [
                        200,
                        { email_exists: false, pending_invite: { organization_name: 'Acme Corp' } },
                    ],
                },
            })
            initKeaTests()
            logic = confirmOrganizationLogic()
            logic.mount()
        })

        it('surfaces a pending invite that precheck finds for the authenticated email', async () => {
            router.actions.push('/organization/confirm-creation', { email: 'alice@acme.com' })

            await expectLogic(logic)
                .toDispatchActions(['setEmail', 'setPendingInvite'])
                .toMatchValues({ pendingInvite: { organization_name: 'Acme Corp' } })
        })
    })
})
