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
})
