import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { navPanelProductPushWelcomeLogic } from './navPanelProductPushWelcomeLogic'
import type { PendingProductPushWelcome } from './navPanelProductPushWelcomeVisibility'

const WEB_ANALYTICS: PendingProductPushWelcome = {
    campaignId: 'campaign-web-analytics',
    productKey: ProductKey.WEB_ANALYTICS,
    label: 'Web analytics',
    text: 'Traffic, referrers, and conversions.',
}

const SESSION_REPLAY: PendingProductPushWelcome = {
    campaignId: 'campaign-session-replay',
    productKey: ProductKey.SESSION_REPLAY,
    label: 'Session replay',
    text: 'Watch real sessions.',
}

describe('navPanelProductPushWelcomeLogic', () => {
    let logic: ReturnType<typeof navPanelProductPushWelcomeLogic.build>

    beforeEach(() => {
        // The seen campaigns persist to localStorage, so clear it or a prior test suppresses
        // the introduction under test.
        window.localStorage.clear()
        initKeaTests()
        logic = navPanelProductPushWelcomeLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The card stays in the nav after the click, so without a per-campaign guard every later click
    // raises the same introduction again.
    it('introduces a campaign once and leaves other campaigns their own introduction', () => {
        logic.actions.setPendingWelcome(WEB_ANALYTICS)
        expect(logic.values.unseenPending).toEqual(WEB_ANALYTICS)

        logic.actions.openWelcome(WEB_ANALYTICS)
        logic.actions.closeWelcome('modal_close')

        // A reload starts from a new kea context, so only what was persisted survives.
        logic.unmount()
        initKeaTests()
        logic = navPanelProductPushWelcomeLogic()
        logic.mount()

        logic.actions.setPendingWelcome(WEB_ANALYTICS)
        expect(logic.values.unseenPending).toBeNull()

        logic.actions.setPendingWelcome(SESSION_REPLAY)
        expect(logic.values.unseenPending).toEqual(SESSION_REPLAY)
    })
})
