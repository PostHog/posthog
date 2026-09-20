import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { productSetupPreloadLogic } from './productSetupPreloadLogic'
import { productSetupStatusLogic } from './productSetupStatusLogic'

describe('productSetupPreloadLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/event_definitions/`]: { count: 0, results: [] },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: true })
    })

    // The boot answer has to agree with the in-scene logic, which reads the team opt-in.
    // While the probe could not read it, an instrumented project with no $exception yet was
    // seeded as `needs-setup` and the setup screen flipped under the user a moment later.
    it('reaches the team opt-in when no $exception definition exists', async () => {
        productSetupPreloadLogic.mount()
        productSetupPreloadLogic.actions.preloadStatuses()
        await expectLogic(productSetupPreloadLogic).toFinishAllListeners()

        expect(productSetupStatusLogic({ productKey: ProductKey.ERROR_TRACKING }).values.status).toEqual(
            'waiting-for-data'
        )
    })
})
