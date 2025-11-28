import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'

import type { feedbackPromptLogicType } from './feedbackPromptLogicType'
import { FeedbackTriggerType } from './utils'

interface FeedbackConfig {
    cooldownMs: number
    messageInterval: number
    samplingRate: number
    retryThreshold: number
    cancelThreshold: number
}

function getFeedbackConfig(): FeedbackConfig | null {
    const payload = getFeatureFlagPayload(FEATURE_FLAGS.POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG)
    if (!payload || typeof payload !== 'object') {
        posthog.captureException(new Error('POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG feature flag is not set'), {
            tags: { product: 'max_ai' },
        })
        return null
    }
    return {
        cooldownMs: payload.cooldownMs,
        messageInterval: payload.messageInterval,
        samplingRate: payload.samplingRate,
        retryThreshold: payload.retryThreshold,
        cancelThreshold: payload.cancelThreshold,
    }
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
        checkShouldShowPrompt: (messageCount: number, retryCount: number, cancelCount: number) => ({
            messageCount,
            retryCount,
            cancelCount,
        }),
        showPrompt: (triggerType: FeedbackTriggerType) => ({ triggerType }),
        hidePrompt: true,
        showDetailedFeedback: true,
        hideDetailedFeedback: true,
        recordFeedbackShown: true,
        setLastTriggeredIntervalIndex: (index: number) => ({ index }),
        submitImplicitDismiss: (conversationId: string, triggerType: FeedbackTriggerType, traceId: string | null) => ({
            conversationId,
            triggerType,
            traceId,
        }),
        submitDetailedFeedbackDismiss: (
            conversationId: string,
            triggerType: FeedbackTriggerType,
            traceId: string | null
        ) => ({
            conversationId,
            triggerType,
            traceId,
        }),
    }),

    reducers({
        isPromptVisible: [
            false,
            {
                showPrompt: () => true,
                hidePrompt: () => false,
                showDetailedFeedback: () => false,
            },
        ],
        isDetailedFeedbackVisible: [
            false,
            {
                showDetailedFeedback: () => true,
                hideDetailedFeedback: () => false,
                hidePrompt: () => false,
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
        canShowPrompt: [
            () => [],
            (): boolean => {
                const config = getFeedbackConfig()
                if (!config) {
                    return false
                }
                const lastShown = localStorage.getItem(STORAGE_KEY)
                if (!lastShown) {
                    return true
                }
                return Date.now() - parseInt(lastShown, 10) > config.cooldownMs
            },
        ],
        messageInterval: [
            () => [],
            (): number => {
                const config = getFeedbackConfig()
                return config?.messageInterval ?? 10
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        checkShouldShowPrompt: ({ messageCount, retryCount, cancelCount }) => {
            const config = getFeedbackConfig()
            if (!config) {
                return
            }

            if (values.isPromptVisible) {
                return
            }

            // Check cooldown directly (selector isn't reactive)
            const lastShown = localStorage.getItem(STORAGE_KEY)
            if (lastShown && Date.now() - parseInt(lastShown, 10) < config.cooldownMs) {
                return
            }

            // Retry threshold - high priority signal
            if (retryCount >= config.retryThreshold) {
                actions.showPrompt('retry')
                return
            }

            // Cancel threshold - high priority signal
            if (cancelCount >= config.cancelThreshold) {
                actions.showPrompt('cancel')
                return
            }

            // Message interval - only trigger once per interval
            if (messageCount > 0 && messageCount % config.messageInterval === 0) {
                const currentIntervalIndex = Math.floor(messageCount / config.messageInterval)
                if (currentIntervalIndex > values.lastTriggeredIntervalIndex) {
                    actions.setLastTriggeredIntervalIndex(currentIntervalIndex)
                    actions.showPrompt('message_interval')
                    return
                }
            }

            // Random sampling
            if (Math.random() < config.samplingRate) {
                actions.showPrompt('random_sample')
            }
        },

        recordFeedbackShown: () => {
            localStorage.setItem(STORAGE_KEY, Date.now().toString())
        },

        submitImplicitDismiss: ({ conversationId, triggerType, traceId }) => {
            posthog.capture('posthog_ai_feedback_submitted', {
                $ai_conversation_id: conversationId,
                $ai_session_id: conversationId,
                $ai_trace_id: traceId,
                $ai_feedback_rating: 'implicit_dismiss',
                $ai_feedback_trigger_type: triggerType,
            })
            actions.recordFeedbackShown()
            actions.hidePrompt()
        },

        submitDetailedFeedbackDismiss: ({ conversationId, triggerType, traceId }) => {
            posthog.capture('posthog_ai_feedback_submitted', {
                $ai_conversation_id: conversationId,
                $ai_session_id: conversationId,
                $ai_trace_id: traceId,
                $ai_feedback_rating: 'bad',
                $ai_feedback_trigger_type: triggerType,
            })
            actions.recordFeedbackShown()
            actions.hideDetailedFeedback()
        },
    })),
])
