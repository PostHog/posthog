import { Region, SLACK_INTEGRATION_SCOPES } from '~/types'

import { requestedScopesForKind } from './integrationScopes'

describe('requestedScopesForKind', () => {
    it.each([
        [Region.US, false, SLACK_INTEGRATION_SCOPES],
        [Region.EU, false, SLACK_INTEGRATION_SCOPES],
        ['E2E', true, SLACK_INTEGRATION_SCOPES],
        [Region.DEV, false, [...SLACK_INTEGRATION_SCOPES, 'channels:join']],
        [null, true, [...SLACK_INTEGRATION_SCOPES, 'channels:join']],
    ])('uses reported OAuth scopes for region %s with debug %s', (region, is_debug, scopes) => {
        const preflight = { region, is_debug, slack_service: { available: true, scopes } }
        const requested = requestedScopesForKind('slack', preflight)

        expect(requested).toEqual(scopes)
        expect(requested).not.toContain('chat:write.public')
    })

    it('does not add Slack scopes to other integrations', () => {
        expect(
            requestedScopesForKind('github', { slack_service: { available: true, scopes: ['channels:join'] } })
        ).toEqual([])
    })

    it('keeps pending scopes out while preflight is unavailable', () => {
        expect(requestedScopesForKind('slack')).toEqual(SLACK_INTEGRATION_SCOPES)
    })

    it('uses approved scopes for older preflight responses', () => {
        expect(requestedScopesForKind('slack', { slack_service: { available: true } })).toEqual(
            SLACK_INTEGRATION_SCOPES
        )
    })
})
