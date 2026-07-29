import { MOCK_TEAM_ID } from 'lib/api.mock'

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

    describe('integration create team scoping', () => {
        let requestedTeamIds: string[]

        beforeEach(() => {
            requestedTeamIds = []
            document.cookie = 'ph_oauth_state=csrf-tok'
            useMocks({
                post: {
                    '/api/environments/:team_id/integrations/': ({ params }) => {
                        requestedTeamIds.push(String(params.team_id))
                        return [201, { id: 7, kind: 'slack' }]
                    },
                },
            })
        })

        afterEach(() => {
            document.cookie = 'ph_oauth_state=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
        })

        it('creates the integration against the team carried in the OAuth state', async () => {
            // The callback is a full-page round-trip on a non-project-scoped URL, so the SPA's
            // current team is the user's default team here (MOCK_TEAM_ID) — not team 228502,
            // which the state says initiated the flow.
            const state = 'next=%2Fproject%2F228502%2Fsettings%2Fproject-integrations&token=csrf-tok&team_id=228502'

            await expectLogic(logic, () => {
                logic.actions.handleOauthCallback('slack' as IntegrationKind, { state, code: 'oauth-code' })
            }).toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith({ kind: 'slack', config: { state, code: 'oauth-code' } }, 228502)
            expect(requestedTeamIds).toEqual(['228502'])
            expect(router.values.location.pathname).toBe('/project/228502/settings/project-integrations')
            expect(router.values.searchParams.integration_id).toBe(7)
        })

        it('falls back to the current team when the OAuth state carries no team_id', async () => {
            // In-flight flows started before team_id was added to the state keep the old behavior.
            const state = 'next=%2Fproject%2F228502%2Fsettings%2Fproject-integrations&token=csrf-tok'

            await expectLogic(logic, () => {
                logic.actions.handleOauthCallback('slack' as IntegrationKind, { state, code: 'oauth-code' })
            }).toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith({ kind: 'slack', config: { state, code: 'oauth-code' } }, undefined)
            expect(requestedTeamIds).toEqual([String(MOCK_TEAM_ID)])
        })
    })
})
