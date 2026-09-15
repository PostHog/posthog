import * as productIntents from 'lib/utils/product-intents'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { navPanelProductPushAdLogic } from './navPanelProductPushAdLogic'
import { navPanelProductPushWelcomeLogic } from './navPanelProductPushWelcomeLogic'

const campaignFor = (productKey: string, productPath: string): ProductPushCampaignApi => ({
    id: '0197c2a2-0000-0000-0000-000000000000',
    product_key: productKey,
    product_path: productPath,
    reason_text: 'Watch real sessions.',
    started_at: '2026-07-01T00:00:00Z',
    ends_at: '2026-07-31T00:00:00Z',
})

describe('navPanelProductPushAdLogic', () => {
    let logic: ReturnType<typeof navPanelProductPushAdLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(productIntents, 'addProductIntent').mockResolvedValue(null)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // The welcome modal follows the click through the navigation it starts, so a click that
    // leaves the app for good must not leave one queued behind for a later, unrelated arrival.
    it.each([
        [
            'a click into the app queues the welcome it will open there',
            ProductKey.SESSION_REPLAY,
            'Session replay',
            true,
        ],
        ['a click that leaves the app queues nothing', ProductKey.POSTHOG_DESKTOP, 'PostHog Desktop', false],
    ])('%s', (_description, productKey, productPath, queued) => {
        logic = navPanelProductPushAdLogic({ campaign: campaignFor(productKey, productPath) })
        logic.mount()

        logic.actions.reportAdClicked()

        expect(navPanelProductPushWelcomeLogic.findMounted()?.values.pending?.productKey ?? null).toBe(
            queued ? productKey : null
        )
    })
})
