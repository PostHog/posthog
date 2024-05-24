import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { createFirstOrganizationLogic } from './createFirstOrganizationLogic'

describe('createFirstOrganizationLogic', () => {
    let logic: ReturnType<typeof createFirstOrganizationLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = createFirstOrganizationLogic()
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
})
