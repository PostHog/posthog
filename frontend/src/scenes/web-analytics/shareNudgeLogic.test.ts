import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { shareNudgeLogic } from './shareNudgeLogic'

const FLAG = FEATURE_FLAGS.WEB_ANALYTICS_SHARE_NUDGE

describe('shareNudgeLogic', () => {
    let logic: ReturnType<typeof shareNudgeLogic.build>

    const enablePromptVariant = (): void => {
        featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: 'prompt' })
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            id: 'org-1',
            name: 'Org',
            member_count: 2,
        } as any)
    }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        organizationLogic.mount()
    })

    afterEach(() => {
        if (logic?.isMounted()) {
            logic.unmount()
        }
        // Restore unconditionally so a failing assertion can't leave a spied-on
        // `document.addEventListener` patched for later test files.
        jest.restoreAllMocks()
    })

    it('selects the prompt variant only when the org has colleagues', async () => {
        enablePromptVariant()
        logic = shareNudgeLogic()
        logic.mount()
        await expectLogic(logic).toMatchValues({ variant: 'prompt', intentPromptEnabled: true })
    })

    // Regression: the prompt variant attaches global `document` mouse listeners. An in-flight
    // mouse event can fire during the teardown window after the logic unmounts — at that point
    // the store path is gone and `cache.disposables` is null. The handlers must stay safe.
    it('does not throw when the captured global handlers fire after unmount', () => {
        const captured: Record<string, (event: any) => void> = {}
        jest.spyOn(document, 'addEventListener').mockImplementation((type, handler) => {
            captured[type] = handler as (event: any) => void
        })

        enablePromptVariant()
        logic = shareNudgeLogic()
        logic.mount()

        expect(captured.mousemove).toBeInstanceOf(Function)
        expect(captured.mouseup).toBeInstanceOf(Function)

        // Simulate the logic tearing down while a mouse event is still in flight.
        logic.unmount()

        const fakeMouseEvent = { target: null, clientX: 10, clientY: 20 }
        expect(() => captured.mousemove(fakeMouseEvent)).not.toThrow()
        expect(() => captured.mouseup(fakeMouseEvent)).not.toThrow()
    })
})
