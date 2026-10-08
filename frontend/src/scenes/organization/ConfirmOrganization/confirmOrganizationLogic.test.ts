import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

const ORGANIZATION_NAME_ERROR =
    "Please enter an organization name. You can use your own name if you don't belong to one."

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
        it('requires a name and an organization name', async () => {
            await expectLogic(logic, () => {
                logic.actions.submitConfirmOrganization()
            }).toMatchValues({
                confirmOrganizationValidationErrors: {
                    first_name: 'Please enter your name',
                    organization_name: ORGANIZATION_NAME_ERROR,
                },
            })
        })

        it.each([
            ['   ', ORGANIZATION_NAME_ERROR],
            ['  Spikes Inc  ', undefined],
        ])('validates the organization name %p on its trimmed value', (organizationName, expectedError) => {
            logic.actions.setConfirmOrganizationValue('organization_name', organizationName)

            expect(logic.values.confirmOrganizationValidationErrors.organization_name).toEqual(expectedError)
        })

        it('shows the organization name error on touch, before any submit', () => {
            expect(logic.values.confirmOrganizationErrors).toEqual({})

            logic.actions.touchConfirmOrganizationField('organization_name')
            expect(logic.values.confirmOrganizationErrors).toEqual({ organization_name: ORGANIZATION_NAME_ERROR })

            logic.actions.setConfirmOrganizationValue('organization_name', 'Spikes Inc')
            expect(logic.values.confirmOrganizationErrors).toEqual({})
        })

        it('puts an API error on the field it names, and lets the next attempt through', async () => {
            useMocks({
                post: {
                    '/api/social_signup/': () => [
                        400,
                        {
                            type: 'validation_error',
                            code: 'invalid_input',
                            detail: 'This name is not allowed.',
                            attr: 'organization_name',
                        },
                    ],
                },
            })
            logic.actions.setConfirmOrganizationValues({ first_name: 'Spike', organization_name: 'Spikes Inc' })

            await expectLogic(logic, () => {
                logic.actions.submitConfirmOrganization()
            }).toFinishAllListeners()

            expect(logic.values.confirmOrganizationErrors).toEqual({ organization_name: 'This name is not allowed.' })

            // A manual error only clears when its own field is touched, so without preSubmit clearing
            // it the person could never retry
            await expectLogic(logic, () => {
                logic.actions.submitConfirmOrganization()
            }).toDispatchActions(['submitConfirmOrganizationRequest'])
        })
    })
})
