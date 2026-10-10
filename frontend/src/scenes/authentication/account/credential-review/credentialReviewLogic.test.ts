import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { credentialReviewLogic } from './credentialReviewLogic'

describe('credentialReviewLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/users/@me/': () => [200, MOCK_DEFAULT_USER],
                '/api/personal_api_keys/': () => [200, []],
                '/api/webauthn/credentials/': () => [200, []],
            },
        })
        initKeaTests()
        userLogic.mount()
        jest.spyOn(api, 'create').mockResolvedValue({})
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    test.each([
        [
            'returns to the page the user was on',
            '/data-warehouse/new-source?kind=Hubspot#configure',
            '/data-warehouse/new-source?kind=Hubspot#configure',
        ],
        ['ignores an off-site next', 'https://example.com/phish', urls.projectHomepage()],
    ])('Continue %s', async (_, next, expectedPath) => {
        router.actions.push(urls.credentialReview(next))
        const logic = credentialReviewLogic()
        logic.mount()

        logic.actions.markComplete()
        await expectLogic(logic).toFinishAllListeners()

        const actualPath = router.values.location.pathname + router.values.location.search + router.values.location.hash
        expect(removeProjectIdIfPresent(actualPath)).toEqual(removeProjectIdIfPresent(expectedPath))
    })
})
