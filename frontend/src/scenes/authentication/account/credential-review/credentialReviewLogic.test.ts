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
                '/api/webauthn/credentials/': () => [200, []],
            },
        })
        initKeaTests()
        userLogic.mount()
        router.actions.push(urls.credentialReview('/inbox/reports/triage'))
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('sends one request and returns to the requested page when Continue is clicked twice', async () => {
        let resolveRequest: (value: unknown) => void = () => {}
        const request = new Promise((resolve) => {
            resolveRequest = resolve
        })
        const createSpy = jest.spyOn(api, 'create').mockReturnValue(request)
        const logic = credentialReviewLogic()
        logic.mount()

        logic.actions.markComplete()
        logic.actions.markComplete()
        expect(logic.values.markCompleteLoading).toBe(true)

        resolveRequest(undefined)
        await expectLogic(logic).toDispatchActions(['markCompleteSuccess']).toMatchValues({
            markCompleteLoading: false,
        })

        expect(createSpy).toHaveBeenCalledTimes(1)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual('/inbox/reports/triage')
    })
})
