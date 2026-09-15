import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { passwordResetLogic } from 'scenes/authentication/password-reset/passwordResetLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('passwordResetLogic', () => {
    let logic: ReturnType<typeof passwordResetLogic.build>
    let resetRequests: Record<string, any>[]

    beforeEach(() => {
        resetRequests = []
        useMocks({
            post: {
                '/api/reset/': async (req) => {
                    resetRequests.push((await req.request.json()) as Record<string, any>)
                    return [200, { success: true }]
                },
            },
        })
        initKeaTests()
        logic = passwordResetLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // The deep link only reaches the person again through the reset email, so the request has to
    // carry it. Without it an OAuth authorization or a Vercel account link is abandoned.
    it.each([
        ['/reset', '/oauth/authorize?client_id=abc', '/oauth/authorize?client_id=abc'],
        ['/reset', 'https://evil.example.com/steal', undefined],
        ['/reset/some-uuid/some-token', '/oauth/authorize?client_id=abc', '/oauth/authorize?client_id=abc'],
    ])('reads the deep link from %s with next=%s', (path, next, expected) => {
        router.actions.push(path, { next })

        expect(logic.values.nextPath).toBe(expected ?? null)
    })

    it('sends the deep link with the reset request', async () => {
        router.actions.push('/reset', { next: '/oauth/authorize?client_id=abc', email: 'user@example.com' })
        logic.actions.submitRequestPasswordReset()
        await expectLogic(logic).toDispatchActions(['submitRequestPasswordResetSuccess'])

        expect(resetRequests).toEqual([{ email: 'user@example.com', next_url: '/oauth/authorize?client_id=abc' }])
    })
})
