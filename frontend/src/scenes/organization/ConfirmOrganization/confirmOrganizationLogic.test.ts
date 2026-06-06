import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

describe('confirmOrganizationLogic', () => {
    let logic: ReturnType<typeof confirmOrganizationLogic.build>

    beforeEach(() => {
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

        it('captures a relative next path so users can log in with another account', async () => {
            router.actions.push('/organization/confirm-creation', {
                email: 'spike@spike.com',
                next: '/project/177329/replay/home',
            })

            await expectLogic(logic).toDispatchActions(['setNext']).toMatchValues({
                next: '/project/177329/replay/home',
            })
        })

        it('rejects an absolute next path pointing at another origin', async () => {
            router.actions.push('/organization/confirm-creation', {
                email: 'spike@spike.com',
                next: 'https://evil.com/steal',
            })

            await expectLogic(logic).toDispatchActions(['setNext']).toMatchValues({
                next: null,
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
})
