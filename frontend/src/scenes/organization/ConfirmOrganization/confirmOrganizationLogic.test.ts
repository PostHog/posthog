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
        it('prefills the form from the URL', async () => {
            router.actions.push('/organization/confirm-creation', {
                email: 'spike@spike.com',
                first_name: 'Spike',
                organization_name: 'Spikes Inc',
            })

            await expectLogic(logic)
                .toDispatchActions(['setEmail', 'setConfirmOrganizationValues'])
                .toMatchValues({
                    confirmOrganization: expect.objectContaining({
                        first_name: 'Spike',
                        organization_name: 'Spikes Inc',
                    }),
                    email: 'spike@spike.com',
                })
        })

        it('keeps user input when a later location change re-fires the handler', async () => {
            router.actions.push('/organization/confirm-creation', { email: 'spike@spike.com' })

            logic.actions.setConfirmOrganizationValue('organization_name', 'Spikes Inc')

            // The docs side panel and similar links change the URL without the prefill params.
            router.actions.push('/organization/confirm-creation', { panel: 'docs' })

            await expectLogic(logic).toMatchValues({
                confirmOrganization: expect.objectContaining({ organization_name: 'Spikes Inc' }),
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
