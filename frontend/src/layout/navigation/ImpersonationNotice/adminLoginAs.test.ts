import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { adminLoginAs } from './adminLoginAs'

describe('adminLoginAs', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('resolves once the session is actually impersonated', async () => {
        useMocks({
            get: {
                '/admin/auth_check': () => [200, {}],
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, id: 7, is_impersonated: true }],
            },
            post: { '/admin/login/user/:id/': () => [200, {}] },
        })

        await expect(adminLoginAs({ userId: 7, reason: 'support ticket', readOnly: true })).resolves.toBeUndefined()
        expect(posthog.capture).not.toHaveBeenCalled()
    })

    // django-loginas answers a refusal with a redirect back to the referer, so the POST still
    // resolves with a 200. Only /api/users/@me/ shows which session the browser holds now: none,
    // or the one the refused attempt failed to replace.
    it.each<[string, Partial<UserType>]>([
        ['no session started', { id: 7, is_impersonated: false }],
        ['the previous user is still impersonated', { id: 3, is_impersonated: true }],
    ])('rejects and captures when the server refuses the impersonation and %s', async (_, meOverrides) => {
        useMocks({
            get: {
                '/admin/auth_check': () => [200, {}],
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, ...meOverrides }],
            },
            post: { '/admin/login/user/:id/': () => [200, {}] },
        })

        await expect(adminLoginAs({ userId: 7, reason: 'support ticket', readOnly: true })).rejects.toThrow(
            /refused the impersonation/
        )
        expect(posthog.capture).toHaveBeenCalledWith('impersonation_failed', {
            cause: 'rejected',
            target_user_id: 7,
            read_only: true,
        })
    })

    it('does not claim the login failed when the confirming request fails', async () => {
        // The POST may already have switched the session, so a lost confirmation is not a refusal.
        useMocks({
            get: {
                '/admin/auth_check': () => [200, {}],
                '/api/users/@me/': () => [500, {}],
            },
            post: { '/admin/login/user/:id/': () => [200, {}] },
        })

        await expect(adminLoginAs({ userId: 7, reason: 'support ticket', readOnly: true })).rejects.toThrow(
            /Reload the page to check/
        )
        expect(posthog.capture).toHaveBeenCalledWith('impersonation_failed', {
            cause: 'verification_failed',
            target_user_id: 7,
            read_only: true,
        })
    })

    it('rejects and captures when the login request itself fails', async () => {
        useMocks({
            get: { '/admin/auth_check': () => [200, {}] },
            post: { '/admin/login/user/:id/': () => [500, {}] },
        })

        await expect(adminLoginAs({ userId: 7, reason: 'support ticket', readOnly: false })).rejects.toThrow(
            /status 500/
        )
        expect(posthog.capture).toHaveBeenCalledWith('impersonation_failed', {
            cause: 'loginas_request_failed',
            target_user_id: 7,
            read_only: false,
        })
    })
})
