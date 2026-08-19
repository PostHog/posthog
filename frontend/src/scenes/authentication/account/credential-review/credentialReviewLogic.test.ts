import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { credentialReviewLogic } from './credentialReviewLogic'

describe('credentialReviewLogic', () => {
    let logic: ReturnType<typeof credentialReviewLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/personal_api_keys/': [],
                '/api/users/@me/two_factor_status/': { is_enabled: false },
            },
        })
        initKeaTests()
        logic = credentialReviewLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('defers to the reauth modal on a stale-session 403 and retries after reauth', async () => {
        const create = jest
            .spyOn(api, 'create')
            .mockRejectedValueOnce(
                new ApiError('reauth required', 403, undefined, { code: 'sensitive_action_required_reauth' })
            )

        // A stale session sets the awaiting flag instead of showing the generic error toast.
        await expectLogic(logic, () => logic.actions.markComplete())
            .toDispatchActions(['setAwaitingReauth'])
            .toMatchValues({ awaitingReauth: true })

        // Once the user re-authenticates, the completion retries and clears the flag.
        create.mockResolvedValueOnce({})
        await expectLogic(logic, () => {
            timeSensitiveAuthenticationLogic.actions.submitReauthenticationSuccess({ password: '' })
        })
            .toDispatchActions(['markComplete', 'setAwaitingReauth'])
            .toMatchValues({ awaitingReauth: false })

        expect(create).toHaveBeenCalledTimes(2)
    })
})
