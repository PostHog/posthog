import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { adminLoginAs } from './adminLoginAs'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

describe('adminLoginAs', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('resolves once the session is actually impersonated', async () => {
        useMocks({
            get: {
                '/admin/auth_check': () => [200, {}],
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, is_impersonated: true }],
            },
            post: { '/admin/login/user/:id/': () => [200, {}] },
        })

        await expect(adminLoginAs({ userId: 7, reason: 'support ticket', readOnly: true })).resolves.toBeUndefined()
        expect(posthog.capture).not.toHaveBeenCalled()
    })

    it('rejects and captures when the server refuses the impersonation', async () => {
        // django-loginas answers a refusal with a redirect back to the referer, so the POST still
        // resolves with a 200. Only /api/users/@me/ shows that the session never changed.
        useMocks({
            get: {
                '/admin/auth_check': () => [200, {}],
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, is_impersonated: false }],
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
