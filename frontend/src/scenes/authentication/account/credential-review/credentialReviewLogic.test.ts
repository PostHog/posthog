import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { credentialReviewLogic } from './credentialReviewLogic'

describe('credentialReviewLogic', () => {
    let logic: ReturnType<typeof credentialReviewLogic.build>

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/personal_api_keys': () => [200, []],
                '/api/webauthn/credentials/': () => [200, []],
            },
        })
        jest.spyOn(api, 'create').mockResolvedValue({})
        logic = credentialReviewLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('returns the user to the carried next destination on complete', async () => {
        router.actions.push('/account/credential-review', { next: '/project/997/insights/abc123' })

        await expectLogic(logic, () => {
            logic.actions.markComplete()
        }).toFinishAllListeners()

        expect(router.values.location.pathname).toBe('/project/997/insights/abc123')
    })

    it('falls back to the project home page when no destination was carried', async () => {
        router.actions.push('/account/credential-review')

        await expectLogic(logic, () => {
            logic.actions.markComplete()
        }).toFinishAllListeners()

        expect(router.values.location.pathname).toBe('/project/997/home')
    })

    describe('backend-only destinations', () => {
        const originalLocation = window.location
        let replaceSpy: jest.Mock

        beforeEach(() => {
            replaceSpy = jest.fn()
            Object.defineProperty(window, 'location', {
                value: { origin: 'http://localhost', replace: replaceSpy },
                configurable: true,
            })
        })

        afterEach(() => {
            Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
        })

        it('does a full page navigation for a backend-only next like the OAuth consent screen', async () => {
            router.actions.push('/account/credential-review', { next: '/oauth/authorize?client_id=abc' })

            await expectLogic(logic, () => {
                logic.actions.markComplete()
            }).toFinishAllListeners()

            // A client-side replace would mount the OAuth scene without the server-injected
            // application metadata and render "No application found".
            expect(replaceSpy).toHaveBeenCalledWith('/oauth/authorize?client_id=abc')
            expect(router.values.location.pathname).toBe('/account/credential-review')
        })
    })
})
