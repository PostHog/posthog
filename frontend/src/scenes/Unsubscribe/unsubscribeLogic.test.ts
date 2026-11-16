import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { unsubscribeLogic } from './unsubscribeLogic'

describe('unsubscribeLogic', () => {
    let requestedTokens: (string | null)[]

    beforeEach(() => {
        requestedTokens = []
        initKeaTests()
    })

    it.each([
        [200, { success: true }, true],
        [500, { detail: 'boom' }, false],
    ])('posts only on confirm, then shows the result (%s)', async (status, body, expected) => {
        useMocks({
            post: {
                '/api/unsubscribe': ({ request }) => {
                    requestedTokens.push(new URL(request.url).searchParams.get('token'))
                    return [status, body]
                },
            },
        })
        router.actions.push('/unsubscribe', { token: 'tok' })
        const logic = unsubscribeLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.unsubscription).toBeNull()
        expect(requestedTokens).toEqual([])

        await expectLogic(logic, () => logic.actions.attemptUnsubscribe()).toFinishAllListeners()

        expect(requestedTokens).toEqual(['tok'])
        expect(logic.values.unsubscription).toBe(expected)
    })
})
