import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { availableSourcesLogic } from '../availableSourcesLogic'

describe('availableSourcesLogic', () => {
    let unmount: () => void

    afterEach(() => {
        unmount?.()
    })

    it('degrades a failed catalog fetch to a null catalog instead of throwing', async () => {
        // This logic mounts on unrelated pages (project settings, onboarding). A non-403 failure
        // must resolve as loadSuccess(null), not loadFailure, so it never throws from the mount hook.
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard/': () => [500, {}],
            },
        })
        initKeaTests()
        unmount = availableSourcesLogic.mount()

        await expectLogic(availableSourcesLogic)
            .toDispatchActions(['load', 'loadSuccess'])
            .toMatchValues({ availableSources: null })
    })
})
