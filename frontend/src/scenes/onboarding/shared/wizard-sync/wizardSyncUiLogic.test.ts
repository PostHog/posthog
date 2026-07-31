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
        logic.actions.claimInlinePanel('local')
        logic.actions.claimInlinePanel('local')
        expect(logic.values.inlineLocalPanelMounted).toBe(true)

        logic.actions.releaseInlinePanel('local')
        expect(logic.values.inlineLocalPanelMounted).toBe(true)

        logic.actions.releaseInlinePanel('local')
        expect(logic.values.inlineLocalPanelMounted).toBe(false)
    })

    it('an extra release does not drive the count negative', () => {
        logic.actions.releaseInlinePanel('local')
        logic.actions.claimInlinePanel('local')
        expect(logic.values.inlineLocalPanelMounted).toBe(true)
    })

    // A local run shown in the inbox rail must not silence the detached surface for a cloud run
    // running alongside it, which would leave the cloud run with no progress, cancel or dismiss.
    it('tracks the two modes separately', () => {
        logic.actions.claimInlinePanel('local')
        expect(logic.values.inlineLocalPanelMounted).toBe(true)
        expect(logic.values.inlineCloudPanelMounted).toBe(false)
        expect(logic.values.inlinePanelMounted).toBe(true)
    })
})
