import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ticketPatternPanelLogic } from './ticketPatternPanelLogic'

describe('ticketPatternPanelLogic', () => {
    let logic: ReturnType<typeof ticketPatternPanelLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/patterns/': () => [
                    200,
                    { results: [], count: 0, next: null, previous: null },
                ],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the patterns for the ticket when the feature flag is on', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_PATTERNS], {
            [FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_PATTERNS]: true,
        })
        logic = ticketPatternPanelLogic({ ticketId: 'a-ticket' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])
    })

    it('loads nothing when the feature flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        logic = ticketPatternPanelLogic({ ticketId: 'a-ticket' })
        logic.mount()

        await expectLogic(logic).toNotHaveDispatchedActions(['loadPatterns'])
    })
})
