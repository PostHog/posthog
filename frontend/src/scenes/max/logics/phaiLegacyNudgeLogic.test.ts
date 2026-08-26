import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'

import { PHAI_LEGACY_NUDGE_DISMISSED_KEY } from '../max-storage-keys'
import { PhaiViewMode, maxGlobalLogic } from '../maxGlobalLogic'
import type { ThreadMessage } from '../maxThreadLogic'
import { maxMocks } from '../testUtils'
import { PhaiLegacyNudgeLogicProps, phaiLegacyNudgeLogic } from './phaiLegacyNudgeLogic'
import { phaiLegacyNudgeStoreLogic } from './phaiLegacyNudgeStoreLogic'

const QUESTION = 'show me weekly signups by source'

const THREAD_WITH_QUESTION = [
    { type: AssistantMessageType.Human, content: QUESTION, status: 'completed' },
] as unknown as ThreadMessage[]

function baseProps(overrides: Partial<PhaiLegacyNudgeLogicProps> = {}): PhaiLegacyNudgeLogicProps {
    return {
        panelId: 'test-panel',
        threadGrouped: THREAD_WITH_QUESTION,
        streamingActive: false,
        isSharedThread: false,
        conversationId: 'conv-1',
        ...overrides,
    }
}

describe('phaiLegacyNudgeLogic', () => {
    let logic: ReturnType<typeof phaiLegacyNudgeLogic.build>

    function mount(
        props: Partial<PhaiLegacyNudgeLogicProps> = {},
        flagOn = true,
        viewMode: PhaiViewMode = 'legacy'
    ): void {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flagOn ? [FEATURE_FLAGS.PHAI_SANDBOX_MODE] : [], {
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: flagOn,
        })
        maxGlobalLogic.mount()
        maxGlobalLogic.actions.setPhaiViewMode(viewMode)
        logic = phaiLegacyNudgeLogic(baseProps(props))
        logic.mount()
    }

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        // The dismissal is persisted, and jest does not clear localStorage between tests, so kea rehydrates
        // one test's dismissal into the next one.
        window.localStorage.removeItem(PHAI_LEGACY_NUDGE_DISMISSED_KEY)
        phaiLegacyNudgeStoreLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // Each `false` row is a state where showing the notice would be wrong in a way a user would notice:
    // interrupting a running answer, appearing on someone else's shared thread, showing up inside the new
    // surface it is advertising, or offering a switch the flag hasn't granted.
    it.each<[string, Partial<PhaiLegacyNudgeLogicProps>, boolean, PhaiViewMode, boolean]>([
        ['a legacy thread that is idle', {}, true, 'legacy', true],
        ['an answer is still streaming', { streamingActive: true }, true, 'legacy', false],
        ['the thread is shared', { isSharedThread: true }, true, 'legacy', false],
        ['the new view is already showing', {}, true, 'new', false],
        ['the sandbox flag is off', {}, false, 'legacy', false],
    ])('shows the notice when %s: %s', (_name, props, flagOn, viewMode, expected) => {
        mount(props, flagOn, viewMode)
        expect(logic.values.shouldShow).toBe(expected)
    })

    it('stops showing the notice once it is dismissed', async () => {
        mount()
        expect(logic.values.shouldShow).toBe(true)

        await expectLogic(logic, () => logic.actions.nudgeDismissed()).toMatchValues({ shouldShow: false })
    })

    // The notice has no impression budget: it stays for as long as someone keeps using the legacy chat, so
    // remounting it (a panel open, a scene tab change, navigating back to /ai) must not wear it out.
    it('keeps showing the notice across remounts', () => {
        mount()
        expect(logic.values.shouldShow).toBe(true)

        logic.unmount()
        logic = phaiLegacyNudgeLogic(baseProps({ panelId: 'another-panel' }))
        logic.mount()

        expect(logic.values.shouldShow).toBe(true)
    })

    it('hands the last question to the new surface when accepted', async () => {
        mount()

        await expectLogic(logic, () => logic.actions.nudgeClicked()).toFinishAllListeners()

        expect(maxGlobalLogic.values.phaiViewMode).toBe('new')
        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(router.values.searchParams.ask).toBe(QUESTION)
    })

    it('switches without a question when the thread is empty', async () => {
        mount({ threadGrouped: [] })
        expect(logic.values.lastHumanQuestion).toBeNull()

        await expectLogic(logic, () => logic.actions.nudgeClicked()).toFinishAllListeners()

        expect(router.values.searchParams.ask).toBeUndefined()
    })

    it('asks why after a dismissal, then closes for good on an answer', async () => {
        mount()

        await expectLogic(logic, () => logic.actions.nudgeDismissed()).toMatchValues({ reasonPromptVisible: true })
        await expectLogic(logic, () => logic.actions.submitReason('broke')).toMatchValues({
            reasonPromptVisible: false,
            dismissed: true,
        })
    })

    it('keeps the prompt open on "Other" so the answer can be typed', async () => {
        mount()
        logic.actions.nudgeDismissed()

        await expectLogic(logic, () => logic.actions.selectOtherReason()).toMatchValues({
            otherReasonSelected: true,
            reasonPromptVisible: true,
        })
    })

    // The typed answer is the only thing the fixed reasons can't carry, so it has to survive trimming and
    // reach the event. Whitespace alone is not an answer and must not report one.
    it.each<[string, string | null]>([
        ['  it forgets what I asked  ', 'it forgets what I asked'],
        ['   ', null],
    ])('reports a typed reason of %p', async (typed, reported) => {
        mount()
        const capture = jest.spyOn(posthog, 'capture')
        logic.actions.nudgeDismissed()
        logic.actions.selectOtherReason()
        logic.actions.setOtherReasonText(typed)

        await expectLogic(logic, () => logic.actions.submitOtherReason()).toFinishAllListeners()

        if (reported) {
            expect(capture).toHaveBeenCalledWith(
                'posthog ai legacy nudge reason',
                expect.objectContaining({ reason: 'other', reason_text: reported })
            )
        } else {
            expect(capture).not.toHaveBeenCalledWith('posthog ai legacy nudge reason', expect.anything())
        }
    })
})
