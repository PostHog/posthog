import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import apiReal from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationKind } from '~/types'

import { integrationsLogic } from './integrationsLogic'

describe('integrationsLogic — handleOauthCallback', () => {
    let logic: ReturnType<typeof integrationsLogic.build>
    let createSpy: jest.SpyInstance

    useMocks({
        get: {
            '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
        },
    })

    beforeEach(() => {
        initKeaTests()
        logic = integrationsLogic()
        logic.mount()
        createSpy = jest.spyOn(apiReal.integrations, 'create')
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('redirects stripe marketplace callbacks to the confirmation page without POSTing', async () => {
        await expectLogic(logic, () => {
            logic.actions.handleOauthCallback('stripe' as IntegrationKind, {
                code: 'ac_123',
                stripe_user_id: 'acct_456',
                account_id: 'acc_789',
                user_id: 'usr_1',
            })
        }).toFinishAllListeners()

        expect(createSpy).not.toHaveBeenCalled()
        expect(router.values.location.pathname).toContain('/integrations/stripe/confirm-install')
        expect(router.values.searchParams).toEqual({
            code: 'ac_123',
            stripe_user_id: 'acct_456',
            account_id: 'acc_789',
            user_id: 'usr_1',
        })
    })

    it('omits empty account_id and user_id when redirecting to the confirmation page', async () => {
        await expectLogic(logic, () => {
            logic.actions.handleOauthCallback('stripe' as IntegrationKind, {
                code: 'ac_123',
                stripe_user_id: 'acct_456',
            })
        }).toFinishAllListeners()

        expect(createSpy).not.toHaveBeenCalled()
        expect(router.values.location.pathname).toContain('/integrations/stripe/confirm-install')
        expect(router.values.searchParams).toEqual({
            code: 'ac_123',
            stripe_user_id: 'acct_456',
        })
    })
})
