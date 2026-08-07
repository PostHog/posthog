import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

describe('confirmOrganizationLogic', () => {
    let logic: ReturnType<typeof confirmOrganizationLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/social_signup/': () => [200, { active: true }],
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

    describe('session gate', () => {
        // The form is only offered once we confirm an active social signup session on this origin, so a
        // stale tab reopened on the other Cloud region falls through to the recovery path instead.
        it('reports the session as active when the check succeeds', async () => {
            await expectLogic(logic).toDispatchActions(['loadSocialSessionSuccess']).toMatchValues({
                sessionState: 'active',
            })
        })

        it('reports the session as inactive when the origin has no active session', async () => {
            // Wait for the on-mount check to settle so it can't overwrite the state we assert next.
            await expectLogic(logic).toDispatchActions(['loadSocialSessionSuccess'])
            await expectLogic(logic, () => {
                logic.actions.loadSocialSessionSuccess({ active: false })
            }).toMatchValues({ sessionState: 'inactive' })
        })
    })
})
