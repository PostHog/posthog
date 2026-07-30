import { initKeaTests } from '~/test/init'

import { wizardSyncUiLogic } from './wizardSyncUiLogic'

describe('wizardSyncUiLogic inline panel refcount', () => {
    let logic: ReturnType<typeof wizardSyncUiLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = wizardSyncUiLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // Two surfaces can show the same run inline (install step + inbox rail); the FAB must stay
    // hidden until the LAST one goes away, and an unbalanced release must not wedge it hidden.
    it('stays claimed until the last panel releases', () => {
        logic.actions.claimInlinePanel()
        logic.actions.claimInlinePanel()
        expect(logic.values.inlinePanelMounted).toBe(true)

        logic.actions.releaseInlinePanel()
        expect(logic.values.inlinePanelMounted).toBe(true)

        logic.actions.releaseInlinePanel()
        expect(logic.values.inlinePanelMounted).toBe(false)
    })

    it('an extra release does not drive the count negative', () => {
        logic.actions.releaseInlinePanel()
        logic.actions.claimInlinePanel()
        expect(logic.values.inlinePanelMounted).toBe(true)
    })
})
