import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

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

    // The one-time auto-open is the feature's contract: the SSE replays the latest session on every
    // connect, so without the seen guard the doc dialog would pop on every reload and navigation.
    // seenHandoffDocKeys persists to localStorage, so each test uses its own doc keys.
    describe('handoff doc auto-open', () => {
        it('opens on the first announcement only, keyed per run', () => {
            logic.actions.handoffDocReceived({ key: 'run-1', text: '# report', startedByEmail: null })
            expect(logic.values.handoffDoc).toEqual({ key: 'run-1', text: '# report' })

            logic.actions.closeHandoffDoc()
            logic.actions.handoffDocReceived({ key: 'run-1', text: '# report', startedByEmail: null })
            expect(logic.values.handoffDoc).toBeNull()

            logic.actions.handoffDocReceived({ key: 'run-2', text: '# other', startedByEmail: null })
            expect(logic.values.handoffDoc).toEqual({ key: 'run-2', text: '# other' })
        })

        it('a doc already read through the button never auto-opens later', () => {
            logic.actions.openHandoffDoc({ key: 'run-3', text: '# report' })
            logic.actions.closeHandoffDoc()

            logic.actions.handoffDocReceived({ key: 'run-3', text: '# report', startedByEmail: null })
            expect(logic.values.handoffDoc).toBeNull()
        })

        it("does not auto-open for a teammate's run", () => {
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

            logic.actions.handoffDocReceived({ key: 'run-4', text: '# report', startedByEmail: 'someone-else@x.com' })
            expect(logic.values.handoffDoc).toBeNull()

            // The runner themselves (or an unattributed run) still gets the auto-open.
            logic.actions.handoffDocReceived({
                key: 'run-5',
                text: '# report',
                startedByEmail: MOCK_DEFAULT_USER.email,
            })
            expect(logic.values.handoffDoc).toEqual({ key: 'run-5', text: '# report' })
        })
    })
})
