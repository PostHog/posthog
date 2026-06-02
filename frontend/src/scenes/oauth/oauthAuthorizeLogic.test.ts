import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

describe('oauthAuthorizeLogic', () => {
    let logic: ReturnType<typeof oauthAuthorizeLogic.build>
    let authorizeResponse: [number, Record<string, any>]

    useMocks({
        get: {
            '/api/projects': () => [200, { results: [] }],
            '/api/organizations/:id/projects': () => [200, { results: [] }],
        },
        post: {
            '/oauth/authorize/': () => authorizeResponse,
        },
    })

    beforeEach(() => {
        initKeaTests()
        authorizeResponse = [200, { redirect_to: 'https://example.com/callback?code=abc&state=s' }]
        logic = oauthAuthorizeLogic()
        logic.mount()
    })

    const navigateToAuthorize = async (scope = 'experiment:write'): Promise<void> => {
        const params = new URLSearchParams({
            client_id: 'test-client-id',
            redirect_uri: 'https://example.com/callback',
            response_type: 'code',
            state: 's',
            scope,
        })
        router.actions.push(`/oauth/authorize?${params.toString()}`)
        await expectLogic(logic).toFinishAllListeners()
    }

    it('surfaces a persistent inline error when /authorize returns invalid_scope (4xx)', async () => {
        await navigateToAuthorize('experiment:write')
        authorizeResponse = [400, { error: 'invalid_scope', error_description: 'Out of bounds' }]

        await expectLogic(logic, () => {
            logic.actions.submitOauthAuthorization()
        }).toFinishAllListeners()

        expect(logic.values.authorizationError).not.toBeNull()
        expect(logic.values.authorizationError?.title).toContain('cannot be granted')
        expect(logic.values.authorizationError?.detail).toEqual('Out of bounds')
        expect(logic.values.authorizationError?.rejectedScopeDescriptions).toEqual(['Write access to experiments'])
        // The submitting flag must reset so the button never appears stuck.
        expect(logic.values.isOauthAuthorizationSubmitting).toBe(false)
    })

    it('surfaces an inline error when invalid_scope is embedded in a 200 redirect_to', async () => {
        await navigateToAuthorize('experiment:write')
        authorizeResponse = [
            200,
            { redirect_to: 'http://localhost:1234/callback?error=invalid_scope&error_description=Nope' },
        ]

        await expectLogic(logic, () => {
            logic.actions.submitOauthAuthorization()
        }).toFinishAllListeners()

        expect(logic.values.authorizationError).not.toBeNull()
        expect(logic.values.authorizationError?.detail).toEqual('Nope')
        // Should not have transitioned to the "Redirecting…" screen.
        expect(logic.values.isRedirecting).toBe(false)
    })

    it('clears a previous error when the form is resubmitted', async () => {
        await navigateToAuthorize('experiment:write')
        authorizeResponse = [400, { error: 'invalid_scope', error_description: 'Out of bounds' }]
        await expectLogic(logic, () => {
            logic.actions.submitOauthAuthorization()
        }).toFinishAllListeners()
        expect(logic.values.authorizationError).not.toBeNull()

        // A subsequent submit clears the stale error before re-attempting.
        authorizeResponse = [400, { error: 'invalid_scope', error_description: 'Still out of bounds' }]
        await expectLogic(logic, () => {
            logic.actions.submitOauthAuthorization()
        })
            .toDispatchActions(['setAuthorizationError'])
            .toFinishAllListeners()
        expect(logic.values.authorizationError?.detail).toEqual('Still out of bounds')
    })
})
