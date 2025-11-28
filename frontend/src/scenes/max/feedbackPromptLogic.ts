import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'

import type { feedbackPromptLogicType } from './feedbackPromptLogicType'
import { maxThreadLogic } from './maxThreadLogic'
import { FeedbackRating, FeedbackTriggerType, captureFeedback } from './utils'

function getMaxThreadLogicValues(): { traceId: string | null; threadGrouped: { type: string }[] } {
    const mountedLogic = maxThreadLogic.findMounted()
    if (!mountedLogic) {
        return { traceId: null, threadGrouped: [] }
    }
    return {
        traceId: mountedLogic.values.traceId,
        threadGrouped: mountedLogic.values.threadGrouped,
    }
}

function resetMaxThreadCounts(): void {
    const mountedLogic = maxThreadLogic.findMounted()
    if (mountedLogic) {
        mountedLogic.actions.resetRetryCount()
        mountedLogic.actions.resetCancelCount()
    }
}

export interface FeedbackConfig {
    cooldownMs: number
    messageInterval: number
    samplingRate: number
    retryThreshold: number
    cancelThreshold: number
}

const STORAGE_KEY = 'posthog_ai_feedback_last_shown'

export interface FeedbackPromptLogicProps {
    conversationId: string
}

export const feedbackPromptLogic = kea<feedbackPromptLogicType>([
    path(['scenes', 'max', 'feedbackPromptLogic']),

    props({} as FeedbackPromptLogicProps),

    key((props) => props.conversationId),

    actions({
        submitRating: (rating: FeedbackRating) => ({ rating }),
        completeDetailedFeedback: true,
        checkShouldShowPrompt: (messageCount: number, retryCount: number, cancelCount: number) => ({
            messageCount,
            retryCount,
            cancelCount,
        }),
        showPrompt: (triggerType: FeedbackTriggerType) => ({ triggerType }),
        hidePrompt: true,
        showDetailedFeedback: true,
        hideDetailedFeedback: true,
        showThankYou: true,
        hideThankYou: true,
        implicitDismissPrompt: true,
        implicitDismissDetailedFeedback: true,
        recordFeedbackShown: true,
        setLastTriggeredIntervalIndex: (index: number) => ({ index }),
    }),

    reducers({
        isPromptVisible: [
            false,
            {
                showPrompt: () => true,
                hidePrompt: () => false,
                implicitDismissPrompt: () => false,
                showDetailedFeedback: () => false,
                showThankYou: () => false,
            },
        ],
        isDetailedFeedbackVisible: [
            false,
            {
                showDetailedFeedback: () => true,
                hideDetailedFeedback: () => false,
                implicitDismissDetailedFeedback: () => false,
                hidePrompt: () => false,
            },
        ],
        isThankYouVisible: [
            false,
            {
                showThankYou: () => true,
                hideThankYou: () => false,
                showPrompt: () => false,
            },
        ],
        currentTriggerType: [
            'manual' as FeedbackTriggerType,
            {
                showPrompt: (_, { triggerType }) => triggerType,
                hidePrompt: () => 'manual' as FeedbackTriggerType,
            },
        ],
        lastTriggeredIntervalIndex: [
            0,
            {
                setLastTriggeredIntervalIndex: (_, { index }) => index,
            },
        ],
    }),

    selectors({
        feedbackConfig: [
            () => [],
            (): FeedbackConfig | null => {
                const payload = getFeatureFlagPayload(FEATURE_FLAGS.POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG)
                if (!payload || typeof payload !== 'object') {
                    posthog.captureException(
                        new Error('POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG feature flag is not set'),
                        { tags: { product: 'max_ai' } }
                    )
                    return null
                }
                return {
                    cooldownMs: payload.cooldownMs,
                    messageInterval: payload.messageInterval,
                    samplingRate: payload.samplingRate,
                    retryThreshold: payload.retryThreshold,
                    cancelThreshold: payload.cancelThreshold,
                }
            },
        ],
        canShowPrompt: [
            (s) => [s.feedbackConfig],
            (feedbackConfig): boolean => {
                if (!feedbackConfig) {
                    return false
                }
                const lastShown = localStorage.getItem(STORAGE_KEY)
                if (!lastShown) {
                    return true
                }
                return Date.now() - parseInt(lastShown, 10) > feedbackConfig.cooldownMs
            },
        ],
        messageInterval: [(s) => [s.feedbackConfig], (feedbackConfig): number => feedbackConfig?.messageInterval ?? 10],
    }),

    listeners(({ actions, values, props }) => ({
        submitRating: ({ rating }) => {
            const { conversationId } = props
            const { currentTriggerType, messageInterval } = values
            const { traceId, threadGrouped } = getMaxThreadLogicValues()

            // For "bad" rating, show the detailed feedback form instead of capturing immediately
            if (rating === 'bad') {
                actions.showDetailedFeedback()
                return
            }

            captureFeedback(conversationId, traceId, rating, currentTriggerType)
            actions.recordFeedbackShown()
            resetMaxThreadCounts()

            // Set the interval index to current level so we don't re-trigger at the same message count
            const humanMessageCount = threadGrouped.filter((m) => m.type === 'human').length
            const currentIntervalIndex = Math.floor(humanMessageCount / messageInterval)
            actions.setLastTriggeredIntervalIndex(currentIntervalIndex)

            // Show thank you for okay/good, just hide for dismissed
            if (rating === 'dismissed') {
                actions.hidePrompt()
            } else {
                actions.showThankYou()
                setTimeout(() => actions.hideThankYou(), 2000)
            }
        },

        checkShouldShowPrompt: ({ messageCount, retryCount, cancelCount }) => {
            const { feedbackConfig } = values
            if (!feedbackConfig) {
                return
            }

            if (values.isPromptVisible) {
                return
            }

            // Check cooldown directly (selector isn't reactive)
            const lastShown = localStorage.getItem(STORAGE_KEY)
            if (lastShown && Date.now() - parseInt(lastShown, 10) < feedbackConfig.cooldownMs) {
                return
            }

            // Retry threshold - high priority signal
            if (retryCount >= feedbackConfig.retryThreshold) {
                actions.showPrompt('retry')
                return
            }

            // Cancel threshold - high priority signal
            if (cancelCount >= feedbackConfig.cancelThreshold) {
                actions.showPrompt('cancel')
                return
            }

            // Message interval - only trigger once per interval
            if (messageCount > 0 && messageCount % feedbackConfig.messageInterval === 0) {
                const currentIntervalIndex = Math.floor(messageCount / feedbackConfig.messageInterval)
                if (currentIntervalIndex > values.lastTriggeredIntervalIndex) {
                    actions.setLastTriggeredIntervalIndex(currentIntervalIndex)
                    actions.showPrompt('message_interval')
                    return
                }
            }

            // Random sampling
            if (Math.random() < feedbackConfig.samplingRate) {
                actions.showPrompt('random_sample')
            }
        },

        recordFeedbackShown: () => {
            localStorage.setItem(STORAGE_KEY, Date.now().toString())
        },

        implicitDismissPrompt: () => {
            const { conversationId } = props
            const { currentTriggerType } = values
            const { traceId } = getMaxThreadLogicValues()

            captureFeedback(conversationId, traceId, 'implicit_dismiss', currentTriggerType)
            actions.recordFeedbackShown()
        },

        implicitDismissDetailedFeedback: () => {
            const { conversationId } = props
            const { currentTriggerType } = values
            const { traceId } = getMaxThreadLogicValues()

            captureFeedback(conversationId, traceId, 'bad', currentTriggerType)
            actions.recordFeedbackShown()
        },

        completeDetailedFeedback: () => {
            const { messageInterval } = values
            const { threadGrouped } = getMaxThreadLogicValues()

            resetMaxThreadCounts()

            const humanMessageCount = threadGrouped.filter((m) => m.type === 'human').length
            const currentIntervalIndex = Math.floor(humanMessageCount / messageInterval)
            actions.setLastTriggeredIntervalIndex(currentIntervalIndex)
            actions.hideDetailedFeedback()
        },
    })),
])
