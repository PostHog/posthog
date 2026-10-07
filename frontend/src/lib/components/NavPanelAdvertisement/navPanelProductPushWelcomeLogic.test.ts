import posthog from 'posthog-js'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { navPanelProductPushWelcomeLogic } from './navPanelProductPushWelcomeLogic'
import type { PendingProductPushWelcome } from './navPanelProductPushWelcomeVisibility'

const WELCOME: PendingProductPushWelcome = {
    campaignId: 'campaign-1',
    productKey: ProductKey.WORKFLOWS,
    label: 'Workflows',
    text: 'Message users when it matters.',
}

describe('navPanelProductPushWelcomeLogic', () => {
    let logic: ReturnType<typeof navPanelProductPushWelcomeLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = navPanelProductPushWelcomeLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('keeps the welcome waiting while a surface holds it, and opens it once the surface lets go', () => {
        const capture = jest.spyOn(posthog, 'capture')
        logic.actions.setPendingWelcome(WELCOME)
        logic.actions.holdWelcome('first-run')

        logic.actions.openWelcome(WELCOME)

        expect(logic.values).toMatchObject({ openFor: null, pending: WELCOME })
        expect(capture).not.toHaveBeenCalled()

        logic.actions.releaseWelcome('first-run')
        logic.actions.openWelcome(WELCOME)

        expect(logic.values).toMatchObject({ openFor: WELCOME, pending: null })
        expect(capture).toHaveBeenCalledWith('nav panel product push welcome shown', expect.anything())
    })

    it('puts an open welcome back on hold when a welcoming surface mounts', () => {
        logic.actions.setPendingWelcome(WELCOME)
        logic.actions.openWelcome(WELCOME)

        logic.actions.holdWelcome('first-run')

        expect(logic.values).toMatchObject({ openFor: null, pending: WELCOME })

        logic.actions.releaseWelcome('first-run')
        logic.actions.openWelcome(WELCOME)

        expect(logic.values).toMatchObject({ openFor: WELCOME, pending: null })
    })
})
