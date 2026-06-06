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

        it.each([
            ['preserves a relative path', '/project/177329/replay/home', '/project/177329/replay/home'],
            ['rejects an absolute off-origin URL', 'https://evil.com/steal', null],
            ['rejects a protocol-relative URL', '//evil.com/steal', null],
            ['falls back to null when next is absent', undefined, null],
        ])('next handling: %s', async (_label, next, expected) => {
            router.actions.push('/organization/confirm-creation', {
                email: 'spike@spike.com',
                ...(next !== undefined ? { next } : {}),
            })

            await expectLogic(logic).toDispatchActions(['setNext']).toMatchValues({
                next: expected,
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
