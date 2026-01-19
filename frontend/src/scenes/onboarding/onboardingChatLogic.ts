import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { OnboardingStepKey, ProductKey } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import type { onboardingChatLogicType } from './onboardingChatLogicType'

export interface OnboardingChatLogicProps {
    productKey?: ProductKey
}

export interface OnboardingStep {
    key: OnboardingStepKey
    title: string
    completed: boolean
}

const onboardingChatLogic = kea<onboardingChatLogicType>([
    path(['scenes', 'onboarding', 'onboardingChatLogic']),
    props({} as OnboardingChatLogicProps),
    key((props) => props.productKey || 'default'),
    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [
            teamLogic,
            ['recordProductIntentOnboardingComplete'],
            eventUsageLogic,
            [
                'reportOnboardingStepCompleted',
                'reportOnboardingStepSkipped',
                'reportOnboardingCompleted',
                'reportAIChatOnboardingStarted',
                'reportAIChatOnboardingMessageSent',
            ],
            maxGlobalLogic,
            ['createConversation'],
        ],
    }),
    actions({
        initializeOnboarding: (productKey: ProductKey) => ({ productKey }),
        completeCurrentStep: (stepKey: OnboardingStepKey, data?: Record<string, any>) => ({ stepKey, data }),
        skipCurrentStep: true,
        moveToNextStep: true,
        setCurrentStep: (stepKey: OnboardingStepKey) => ({ stepKey }),
        updateStepData: (stepKey: OnboardingStepKey, data: Record<string, any>) => ({ stepKey, data }),
        setStepCompleted: (stepKey: OnboardingStepKey) => ({ stepKey }),
        finishOnboarding: true,
    }),
    reducers(({ props }) => ({
        productKey: [
            props.productKey || null,
            {
                initializeOnboarding: (_, { productKey }) => productKey,
            },
        ],
        currentStep: [
            null as OnboardingStepKey | null,
            {
                setCurrentStep: (_, { stepKey }) => stepKey,
                moveToNextStep: (state, _, { allSteps, currentStepIndex }) => {
                    const nextIndex = currentStepIndex + 1
                    return nextIndex < allSteps.length ? allSteps[nextIndex].key : null
                },
            },
        ],
        completedSteps: [
            [] as OnboardingStepKey[],
            {
                setStepCompleted: (state, { stepKey }) => [...state, stepKey],
            },
        ],
        stepData: [
            {} as Record<OnboardingStepKey, Record<string, any>>,
            {
                updateStepData: (state, { stepKey, data }) => ({
                    ...state,
                    [stepKey]: { ...(state[stepKey] || {}), ...data },
                }),
            },
        ],
        conversationId: [
            null as string | null,
            {
                initializeOnboarding: () => `onboarding-${Date.now()}`,
            },
        ],
    })),
    selectors({
        allSteps: [
            (s) => [s.productKey],
            (productKey): OnboardingStep[] => {
                if (!productKey) {
                    return []
                }

                // Map of product-specific onboarding steps
                // These mirror the existing onboarding flow in Onboarding.tsx
                const productSteps: Record<ProductKey, OnboardingStepKey[]> = {
                    product_analytics: [
                        OnboardingStepKey.INSTALL,
                        OnboardingStepKey.PRODUCT_CONFIGURATION,
                        OnboardingStepKey.SESSION_REPLAY,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                    session_replay: [
                        OnboardingStepKey.INSTALL,
                        OnboardingStepKey.PRODUCT_CONFIGURATION,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                    feature_flags: [
                        OnboardingStepKey.INSTALL,
                        OnboardingStepKey.REVERSE_PROXY,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                    experiments: [
                        OnboardingStepKey.INSTALL,
                        OnboardingStepKey.REVERSE_PROXY,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                    surveys: [
                        OnboardingStepKey.INSTALL,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                    web_analytics: [
                        OnboardingStepKey.INSTALL,
                        OnboardingStepKey.AUTHORIZED_DOMAINS,
                        OnboardingStepKey.PRODUCT_CONFIGURATION,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                    error_tracking: [
                        OnboardingStepKey.INSTALL,
                        OnboardingStepKey.SOURCE_MAPS,
                        OnboardingStepKey.ALERTS,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                    data_warehouse: [
                        OnboardingStepKey.LINK_DATA,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                    llm_analytics: [
                        OnboardingStepKey.INSTALL,
                        OnboardingStepKey.AI_CONSENT,
                        OnboardingStepKey.INVITE_TEAMMATES,
                    ],
                }

                const steps = productSteps[productKey] || []
                return steps.map((key) => ({
                    key,
                    title: getStepTitle(key),
                    completed: false,
                }))
            },
        ],
        currentStepIndex: [
            (s) => [s.currentStep, s.allSteps],
            (currentStep, allSteps) => {
                if (!currentStep) {
                    return 0
                }
                return allSteps.findIndex((step) => step.key === currentStep)
            },
        ],
        isOnboardingComplete: [
            (s) => [s.completedSteps, s.allSteps],
            (completedSteps, allSteps) => {
                return completedSteps.length >= allSteps.length
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        initializeOnboarding: async ({ productKey }) => {
            // Report that AI chat onboarding started
            actions.reportAIChatOnboardingStarted(productKey)

            // Start with the first step
            if (values.allSteps.length > 0) {
                actions.setCurrentStep(values.allSteps[0].key)
            }

            // Create a conversation in onboarding mode
            if (values.conversationId) {
                actions.createConversation({
                    conversation_id: values.conversationId,
                    agent_mode: AgentMode.Onboarding,
                    initial_message: `Hi! I'm here to help you get started with ${getProductName(productKey)}. Let's walk through the setup together.`,
                })
            }
        },
        completeCurrentStep: async ({ stepKey, data }) => {
            // Update step data if provided
            if (data) {
                actions.updateStepData(stepKey, data)
            }

            // Mark step as completed
            actions.setStepCompleted(stepKey)

            // Report completion
            actions.reportOnboardingStepCompleted(stepKey)

            // Check if onboarding is complete
            if (values.isOnboardingComplete) {
                actions.finishOnboarding()
            } else {
                // Move to next step
                actions.moveToNextStep()
            }
        },
        skipCurrentStep: async () => {
            if (values.currentStep) {
                actions.reportOnboardingStepSkipped(values.currentStep)
                actions.setStepCompleted(values.currentStep)

                if (values.isOnboardingComplete) {
                    actions.finishOnboarding()
                } else {
                    actions.moveToNextStep()
                }
            }
        },
        finishOnboarding: async () => {
            if (values.productKey) {
                // Mark product onboarding as complete
                await actions.recordProductIntentOnboardingComplete(values.productKey)

                // Report onboarding completion
                actions.reportOnboardingCompleted('ai_chat_onboarding')
            }
        },
    })),
])

// Helper functions
function getStepTitle(stepKey: OnboardingStepKey): string {
    const titles: Record<OnboardingStepKey, string> = {
        [OnboardingStepKey.INSTALL]: 'Install PostHog',
        [OnboardingStepKey.PRODUCT_CONFIGURATION]: 'Configure features',
        [OnboardingStepKey.SESSION_REPLAY]: 'Session replay',
        [OnboardingStepKey.REVERSE_PROXY]: 'Reverse proxy',
        [OnboardingStepKey.AUTHORIZED_DOMAINS]: 'Authorized domains',
        [OnboardingStepKey.SOURCE_MAPS]: 'Source maps',
        [OnboardingStepKey.ALERTS]: 'Configure alerts',
        [OnboardingStepKey.AI_CONSENT]: 'AI features',
        [OnboardingStepKey.INVITE_TEAMMATES]: 'Invite teammates',
        [OnboardingStepKey.LINK_DATA]: 'Link data source',
        [OnboardingStepKey.PLANS]: 'Choose plan',
        [OnboardingStepKey.VERIFY]: 'Verify setup',
        [OnboardingStepKey.TELL_US_MORE]: 'Tell us more',
    }
    return titles[stepKey] || stepKey
}

function getProductName(productKey: ProductKey): string {
    const names: Record<ProductKey, string> = {
        product_analytics: 'Product analytics',
        session_replay: 'Session replay',
        feature_flags: 'Feature flags',
        experiments: 'Experiments',
        surveys: 'Surveys',
        web_analytics: 'Web analytics',
        error_tracking: 'Error tracking',
        data_warehouse: 'Data warehouse',
        llm_analytics: 'LLM analytics',
    }
    return names[productKey] || productKey
}

export { onboardingChatLogic }
