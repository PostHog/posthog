import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

jest.mock('posthog-js')

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

    describe('with a failed precheck', () => {
        beforeEach(() => {
            useMocks({
                post: {
                    '/api/signup/precheck': () => [500, {}],
                },
            })
            initKeaTests()
            logic = confirmOrganizationLogic()
            logic.mount()
            ;(posthog.capture as jest.Mock).mockClear()
        })

        it('records has_pending_invite as null so a swallowed failure is not counted as no invite', async () => {
            router.actions.push('/organization/confirm-creation', { email: 'spike@spike.com' })

            await expectLogic(logic).toDispatchActions(['setEmail']).toFinishAllListeners()

            const shownEvents = (posthog.capture as jest.Mock).mock.calls.filter(
                ([event]) => event === 'organization creation confirmation shown'
            )
            expect(shownEvents).toHaveLength(1)
            expect(shownEvents[0][1]).toEqual({ has_pending_invite: null })
        })
    })
})
