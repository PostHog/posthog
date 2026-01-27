import { expectLogic } from 'kea-test-utils'

import * as featureFlagLogic from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { feedbackPromptLogic } from './feedbackPromptLogic'

const MOCK_CONVERSATION_ID = 'test-conversation-123'

const DEFAULT_CONFIG = {
    cooldownMs: 86400000, // 24 hours
    messageInterval: 10,
    samplingRate: 0.05,
    retryThreshold: 2,
    cancelThreshold: 3,
}

describe('feedbackPromptLogic', () => {
    let logic: ReturnType<typeof feedbackPromptLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()

        // Mock the feature flag payload
        jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(DEFAULT_CONFIG)

        logic = feedbackPromptLogic({ conversationId: MOCK_CONVERSATION_ID })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
        localStorage.clear()
    })

    describe('checkShouldShowPrompt', () => {
        it('does not show prompt when config is not available', async () => {
            jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(null)

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10, 0, 0)
            }).toMatchValues({
                isPromptVisible: false,
            })
        })

        it('does not show prompt when already visible', async () => {
            logic.actions.showPrompt('manual')

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10, 5, 5)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'manual', // Should not change
            })
        })

        it('does not show prompt when cooldown is active', async () => {
            // Set cooldown to recently shown
            localStorage.setItem('posthog_ai_feedback_last_shown', Date.now().toString())

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10, 5, 5)
            }).toMatchValues({
                isPromptVisible: false,
            })
        })

        it('shows prompt with retry trigger when retry threshold is reached', async () => {
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(5, 2, 0)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'retry',
            })
        })

        it('shows prompt with cancel trigger when cancel threshold is reached', async () => {
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(5, 0, 3)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'cancel',
            })
        })

        it('retry trigger takes priority over cancel trigger', async () => {
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(5, 2, 3)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'retry',
            })
        })

        it('shows prompt with message_interval trigger at correct intervals', async () => {
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10, 0, 0)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'message_interval',
                lastTriggeredIntervalIndex: 1,
            })
        })

        it('does not trigger message_interval twice for same interval', async () => {
            // Mock Math.random to avoid random sampling trigger
            jest.spyOn(Math, 'random').mockReturnValue(0.9)

            // First trigger at message 10
            logic.actions.checkShouldShowPrompt(10, 0, 0)
            expect(logic.values.isPromptVisible).toBe(true)
            expect(logic.values.lastTriggeredIntervalIndex).toBe(1)

            // Hide prompt and try again at same message count
            logic.actions.hidePrompt()

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10, 0, 0)
            }).toMatchValues({
                isPromptVisible: false,
                lastTriggeredIntervalIndex: 1,
            })
        })

        it('triggers message_interval at next interval', async () => {
            // Mock Math.random to avoid random sampling trigger
            jest.spyOn(Math, 'random').mockReturnValue(0.9)

            // First trigger at message 10
            logic.actions.checkShouldShowPrompt(10, 0, 0)
            logic.actions.hidePrompt()

            // Should trigger at message 20
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(20, 0, 0)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'message_interval',
                lastTriggeredIntervalIndex: 2,
            })
        })

        it('does not show prompt when message count is not at interval', async () => {
            // Mock Math.random to return a value above sampling rate
            jest.spyOn(Math, 'random').mockReturnValue(0.9)

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(7, 0, 0)
            }).toMatchValues({
                isPromptVisible: false,
            })
        })
    })

    describe('showPrompt and hidePrompt', () => {
        it('showPrompt sets isPromptVisible and currentTriggerType', async () => {
            await expectLogic(logic, () => {
                logic.actions.showPrompt('retry')
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'retry',
            })
        })

        it('hidePrompt resets visibility and trigger type', async () => {
            logic.actions.showPrompt('cancel')

            await expectLogic(logic, () => {
                logic.actions.hidePrompt()
            }).toMatchValues({
                isPromptVisible: false,
                currentTriggerType: 'manual',
            })
        })
    })

    describe('recordFeedbackShown', () => {
        it('sets localStorage timestamp', async () => {
            const beforeTime = Date.now()

            await expectLogic(logic, () => {
                logic.actions.recordFeedbackShown()
            })

            const storedTime = parseInt(localStorage.getItem('posthog_ai_feedback_last_shown') || '0', 10)
            expect(storedTime).toBeGreaterThanOrEqual(beforeTime)
            expect(storedTime).toBeLessThanOrEqual(Date.now())
        })
    })

    describe('setLastTriggeredIntervalIndex', () => {
        it('updates lastTriggeredIntervalIndex', async () => {
            await expectLogic(logic, () => {
                logic.actions.setLastTriggeredIntervalIndex(5)
            }).toMatchValues({
                lastTriggeredIntervalIndex: 5,
            })
        })
    })

    describe('messageInterval selector', () => {
        it('returns messageInterval from config', () => {
            expect(logic.values.messageInterval).toBe(10)
        })

        it('returns default value when config is null', () => {
            jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(null)

            // Need to remount to pick up the new mock
            logic.unmount()
            logic = feedbackPromptLogic({ conversationId: MOCK_CONVERSATION_ID })
            logic.mount()

            expect(logic.values.messageInterval).toBe(10) // default fallback
        })
    })

    describe('canShowPrompt selector', () => {
        it('returns true when no cooldown is active', () => {
            expect(logic.values.canShowPrompt).toBe(true)
        })

        it('returns false when cooldown is active', () => {
            localStorage.setItem('posthog_ai_feedback_last_shown', Date.now().toString())

            // Need to remount to pick up the new localStorage value
            logic.unmount()
            logic = feedbackPromptLogic({ conversationId: MOCK_CONVERSATION_ID })
            logic.mount()

            expect(logic.values.canShowPrompt).toBe(false)
        })

        it('returns true when cooldown has expired', () => {
            // Set cooldown to 25 hours ago (longer than 24 hour cooldown)
            const expiredTime = Date.now() - 25 * 60 * 60 * 1000
            localStorage.setItem('posthog_ai_feedback_last_shown', expiredTime.toString())

            logic.unmount()
            logic = feedbackPromptLogic({ conversationId: MOCK_CONVERSATION_ID })
            logic.mount()

            expect(logic.values.canShowPrompt).toBe(true)
        })

        it('returns false when config is not available', () => {
            jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(null)

            logic.unmount()
            logic = feedbackPromptLogic({ conversationId: MOCK_CONVERSATION_ID })
            logic.mount()

            expect(logic.values.canShowPrompt).toBe(false)
        })
    })

    describe('per-conversation isolation', () => {
        it('maintains separate state for different conversations', async () => {
            const logic1 = feedbackPromptLogic({ conversationId: 'conversation-1' })
            const logic2 = feedbackPromptLogic({ conversationId: 'conversation-2' })

            logic1.mount()
            logic2.mount()

            // Show prompt on conversation 1
            logic1.actions.showPrompt('retry')
            logic1.actions.setLastTriggeredIntervalIndex(3)

            expect(logic1.values.isPromptVisible).toBe(true)
            expect(logic1.values.lastTriggeredIntervalIndex).toBe(3)

            // Conversation 2 should be independent
            expect(logic2.values.isPromptVisible).toBe(false)
            expect(logic2.values.lastTriggeredIntervalIndex).toBe(0)

            logic1.unmount()
            logic2.unmount()
        })
    })
})
