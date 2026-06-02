import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import apiReal from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

describe('oauthAuthorizeLogic', () => {
    let logic: ReturnType<typeof oauthAuthorizeLogic.build>
    let createSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        // loadAllTeams runs on mount (via urlToAction); keep it off the network.
        jest.spyOn(apiReal, 'loadPaginatedResults').mockResolvedValue([])
        createSpy = jest
            .spyOn(apiReal, 'create')
            .mockResolvedValue({ redirect_to: 'https://example.com/callback?code=abc&state=s' })

        const params = new URLSearchParams({
            client_id: 'test-client-id',
            redirect_uri: 'https://example.com/callback',
            response_type: 'code',
            state: 's',
            scope: 'experiment:write',
        })
        router.actions.push(`/oauth/authorize?${params.toString()}`)
        logic = oauthAuthorizeLogic()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const invalidScopeApiError = (description: string): ApiError =>
        new ApiError('invalid_scope', 400, undefined, { error: 'invalid_scope', error_description: description })

    it('surfaces a persistent inline error when /authorize returns invalid_scope (4xx)', async () => {
        await expectLogic(logic).toFinishAllListeners()
        createSpy.mockRejectedValue(invalidScopeApiError('Out of bounds'))

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
        await expectLogic(logic).toFinishAllListeners()
        createSpy.mockResolvedValue({
            redirect_to: 'http://localhost:1234/callback?error=invalid_scope&error_description=Nope',
        })

        await expectLogic(logic, () => {
            logic.actions.submitOauthAuthorization()
        }).toFinishAllListeners()

        expect(logic.values.authorizationError).not.toBeNull()
        expect(logic.values.authorizationError?.detail).toEqual('Nope')
        // Should not have transitioned to the "Redirecting…" screen.
        expect(logic.values.isRedirecting).toBe(false)
    })

    it('clears a previous error when the form is resubmitted', async () => {
        await expectLogic(logic).toFinishAllListeners()
        createSpy.mockRejectedValue(invalidScopeApiError('Out of bounds'))
        await expectLogic(logic, () => {
            logic.actions.submitOauthAuthorization()
        }).toFinishAllListeners()
        expect(logic.values.authorizationError?.detail).toEqual('Out of bounds')

        // A subsequent submit clears the stale error before re-attempting.
        createSpy.mockRejectedValue(invalidScopeApiError('Still out of bounds'))
        await expectLogic(logic, () => {
            logic.actions.submitOauthAuthorization()
        })
            .toDispatchActions(['setAuthorizationError'])
            .toFinishAllListeners()
        expect(logic.values.authorizationError?.detail).toEqual('Still out of bounds')
    })
})
