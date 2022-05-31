import { confirmOrganizationLogic } from './confirmOrganizationLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'

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
            })

            expectLogic(logic)
                .toDispatchActions(['setEmail', 'setConfirmOrganizationValues'])
                .toMatchValues({
                    confirmOrganization: {
                        first_name: 'Spike',
                        organization_name: 'Spikes Inc',
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
