import { useActions } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { ProductKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'

interface OnboardingMessage {
    role: 'assistant' | 'user'
    content: string
    options?: { label: string; value: string; description?: string }[]
}

type OnboardingPhase = 'discovery' | 'product_selection' | 'setup'

const INITIAL_MESSAGE: OnboardingMessage = {
    role: 'assistant',
    content:
        "Hi! 👋 I'm here to help you get the most out of PostHog. Tell me a bit about what you're working on - what's your main goal right now?",
    options: [
        {
            label: 'Understand user behavior',
            value: 'understand_users',
            description: 'Track events, analyze funnels, see how users navigate',
        },
        {
            label: 'Find and fix issues',
            value: 'fix_issues',
            description: 'Watch session recordings, catch errors',
        },
        {
            label: 'Run experiments',
            value: 'experiments',
            description: 'A/B tests, feature flags, gradual rollouts',
        },
        {
            label: 'Something else',
            value: 'other',
            description: "I'll explain what I need",
        },
    ],
}

const GOAL_RESPONSES: Record<string, OnboardingMessage> = {
    understand_users: {
        role: 'assistant',
        content:
            "Great! To understand user behavior, I'd recommend starting with **Product analytics** - it'll help you track events, build funnels, and see user journeys.\n\nWould you also like to enable **Session replay** to watch real user sessions? It's super helpful for understanding *why* users do what they do.",
        options: [
            { label: 'Yes, both sound great!', value: 'analytics_and_replay' },
            { label: 'Just analytics for now', value: 'analytics_only' },
            { label: 'Tell me more about session replay', value: 'explain_replay' },
        ],
    },
    fix_issues: {
        role: 'assistant',
        content:
            "Perfect for debugging! I'd recommend:\n\n• **Session replay** - Watch exactly what users experienced\n• **Error tracking** - Catch and fix exceptions automatically\n\nBoth together give you the full picture when something goes wrong.",
        options: [
            { label: 'Set up both', value: 'replay_and_errors' },
            { label: 'Just session replay', value: 'replay_only' },
            { label: 'Just error tracking', value: 'errors_only' },
        ],
    },
    experiments: {
        role: 'assistant',
        content:
            "Love it! For experimentation, you'll want:\n\n• **Feature flags** - Control who sees what, roll out gradually\n• **Experiments** - Run A/B tests with statistical analysis\n\nFeature flags are the foundation - experiments build on top of them.",
        options: [
            { label: 'Set up both', value: 'flags_and_experiments' },
            { label: 'Start with feature flags', value: 'flags_only' },
            { label: 'Tell me more about experiments', value: 'explain_experiments' },
        ],
    },
    other: {
        role: 'assistant',
        content:
            "No problem! Tell me more about what you're building or what problem you're trying to solve, and I'll point you in the right direction.",
        options: [
            { label: 'I want to collect user feedback', value: 'feedback' },
            { label: 'I need website analytics', value: 'web_analytics' },
            { label: 'I want to monitor my AI/LLM app', value: 'llm' },
        ],
    },
    feedback: {
        role: 'assistant',
        content:
            "**Surveys** is perfect for that! You can create in-app surveys to collect feedback at the right moment - after a purchase, when someone's about to churn, or just to understand sentiment.",
        options: [
            { label: "Let's set up surveys", value: 'setup_surveys' },
            { label: 'Can I also watch user sessions?', value: 'surveys_and_replay' },
        ],
    },
    web_analytics: {
        role: 'assistant',
        content:
            '**Web analytics** gives you a privacy-friendly, cookieless way to understand your website traffic - pageviews, referrers, top pages, and more. Think of it as a simpler Google Analytics alternative.',
        options: [
            { label: "Let's set it up", value: 'setup_web_analytics' },
            { label: 'I also want deeper product analytics', value: 'web_and_product' },
        ],
    },
    llm: {
        role: 'assistant',
        content:
            '**LLM analytics** helps you monitor your AI application - track costs, latency, token usage, and analyze conversations. Perfect for understanding how users interact with your AI features.',
        options: [
            { label: "Let's set it up", value: 'setup_llm' },
            { label: 'Tell me more', value: 'explain_llm' },
        ],
    },
}

const PRODUCT_MAPPING: Record<string, ProductKey[]> = {
    analytics_and_replay: ['product_analytics', 'session_replay'],
    analytics_only: ['product_analytics'],
    replay_and_errors: ['session_replay', 'error_tracking'],
    replay_only: ['session_replay'],
    errors_only: ['error_tracking'],
    flags_and_experiments: ['feature_flags', 'experiments'],
    flags_only: ['feature_flags'],
    setup_surveys: ['surveys'],
    surveys_and_replay: ['surveys', 'session_replay'],
    setup_web_analytics: ['web_analytics'],
    web_and_product: ['web_analytics', 'product_analytics'],
    setup_llm: ['llm_analytics'],
}

export function OnboardingChat(): JSX.Element {
    const { setProductKey, completeOnboarding } = useActions(onboardingLogic)
    const [messages, setMessages] = useState<OnboardingMessage[]>([INITIAL_MESSAGE])
    const [inputValue, setInputValue] = useState('')
    const [phase, setPhase] = useState<OnboardingPhase>('discovery')
    const [selectedProducts, setSelectedProducts] = useState<ProductKey[]>([])
    const [currentSetupStep, setCurrentSetupStep] = useState(0)

    useEffect(() => {
        // Track AI chat onboarding started
        window.posthog?.capture('ai chat onboarding started', {
            phase: 'discovery',
        })
    }, [])

    const handleOptionClick = (value: string, label: string): void => {
        // Add user message
        const userMessage: OnboardingMessage = { role: 'user', content: label }
        setMessages((prev) => [...prev, userMessage])

        // Track interaction
        window.posthog?.capture('ai chat onboarding message sent', {
            phase,
            message_type: 'button',
            value,
        })

        // Check if this maps to products (user is ready to set up)
        if (PRODUCT_MAPPING[value]) {
            const products = PRODUCT_MAPPING[value]
            setSelectedProducts(products)
            setPhase('setup')

            setTimeout(() => {
                const setupMessage: OnboardingMessage = {
                    role: 'assistant',
                    content: `Excellent choice! Let's get ${products.length > 1 ? 'these' : 'this'} set up.\n\nFirst, I'll need to know which platform you're building on so I can give you the right installation instructions.`,
                    options: [
                        { label: 'JavaScript / Web', value: 'js' },
                        { label: 'React', value: 'react' },
                        { label: 'Next.js', value: 'nextjs' },
                        { label: 'Other', value: 'other_platform' },
                    ],
                }
                setMessages((prev) => [...prev, setupMessage])

                // Set the first product as active
                if (products[0]) {
                    setProductKey(products[0])
                }
            }, 500)
            return
        }

        // Handle follow-up questions
        if (GOAL_RESPONSES[value]) {
            setTimeout(() => {
                setMessages((prev) => [...prev, GOAL_RESPONSES[value]])
            }, 500)
            return
        }

        // Handle setup flow responses
        if (phase === 'setup') {
            handleSetupResponse(value)
        }
    }

    const handleSetupResponse = (value: string): void => {
        const setupSteps = [
            {
                message:
                    "Got it! Here's what you need to do:\n\n1. Install the PostHog snippet in your app\n2. Initialize it with your project API key\n\nI've pre-configured the recommended settings. Would you like to customize anything?",
                options: [
                    { label: 'Looks good, continue', value: 'continue_setup' },
                    { label: 'Show me the settings', value: 'show_settings' },
                ],
            },
            {
                message:
                    'Almost there! Would you like to enable **autocapture**? It automatically tracks clicks, form submissions, and pageviews without any extra code.',
                options: [
                    { label: 'Yes, enable autocapture', value: 'enable_autocapture' },
                    { label: "No, I'll track events manually", value: 'manual_tracking' },
                ],
            },
            {
                message:
                    "🎉 You're all set! Your PostHog installation is configured and ready to go.\n\nOnce you deploy your changes, data will start flowing in. Want me to show you around the dashboard?",
                options: [
                    { label: 'Yes, show me around', value: 'complete_tour' },
                    { label: "I'm good, let me explore", value: 'complete_explore' },
                ],
            },
        ]

        if (value === 'complete_tour' || value === 'complete_explore') {
            handleComplete()
            return
        }

        if (currentSetupStep < setupSteps.length) {
            setTimeout(() => {
                setMessages((prev) => [...prev, { role: 'assistant', ...setupSteps[currentSetupStep] }])
                setCurrentSetupStep((prev) => prev + 1)
            }, 500)
        }
    }

    const handleSendMessage = (): void => {
        if (!inputValue.trim()) {
            return
        }

        const userMessage: OnboardingMessage = { role: 'user', content: inputValue }
        setMessages((prev) => [...prev, userMessage])
        setInputValue('')

        // Track interaction
        window.posthog?.capture('ai chat onboarding message sent', {
            phase,
            message_type: 'chat',
        })

        // Simple response for free-form input
        setTimeout(() => {
            const response: OnboardingMessage = {
                role: 'assistant',
                content:
                    "Thanks for sharing! Based on what you've described, let me suggest some products that could help.",
                options: [
                    { label: 'Understand user behavior', value: 'understand_users' },
                    { label: 'Find and fix issues', value: 'fix_issues' },
                    { label: 'Run experiments', value: 'experiments' },
                ],
            }
            setMessages((prev) => [...prev, response])
        }, 500)
    }

    const handleComplete = (): void => {
        window.posthog?.capture('ai chat onboarding completed', {
            products_selected: selectedProducts,
        })
        completeOnboarding()
    }

    const totalSteps = phase === 'discovery' ? 3 : 5
    const currentStep = phase === 'discovery' ? Math.min(messages.length, 3) : currentSetupStep + 3

    return (
        <div className="flex flex-col h-[80vh] max-w-3xl mx-auto">
            {/* Header with progress */}
            <div className="border-b p-4">
                <div className="flex items-center justify-between mb-2">
                    <h2 className="text-xl font-semibold">Welcome to PostHog</h2>
                    <span className="text-sm text-muted">
                        {phase === 'discovery' ? 'Getting to know you' : 'Setting up'}
                    </span>
                </div>
                <div className="w-full bg-border rounded-full h-2">
                    <div
                        className="bg-primary h-2 rounded-full transition-all"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${(currentStep / totalSteps) * 100}%` }}
                    />
                </div>
            </div>

            {/* Chat messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.map((message, index) => (
                    <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div
                            className={`max-w-[85%] rounded-lg p-4 ${
                                message.role === 'user' ? 'bg-primary text-primary-inverse' : 'bg-bg-light border'
                            }`}
                        >
                            <p className="whitespace-pre-wrap">{message.content}</p>

                            {/* Option buttons */}
                            {message.options && message.role === 'assistant' && index === messages.length - 1 && (
                                <div className="flex flex-col gap-2 mt-4">
                                    {message.options.map((option) => (
                                        <LemonButton
                                            key={option.value}
                                            type="secondary"
                                            size="medium"
                                            fullWidth
                                            onClick={() => handleOptionClick(option.value, option.label)}
                                            className="justify-start text-left"
                                        >
                                            <div>
                                                <div className="font-medium">{option.label}</div>
                                                {option.description && (
                                                    <div className="text-xs text-muted mt-0.5">
                                                        {option.description}
                                                    </div>
                                                )}
                                            </div>
                                        </LemonButton>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            {/* Input area */}
            <div className="border-t p-4">
                <div className="flex gap-2">
                    <LemonTextArea
                        value={inputValue}
                        onChange={(value) => setInputValue(value)}
                        placeholder="Or type your own response..."
                        className="flex-1"
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault()
                                handleSendMessage()
                            }
                        }}
                    />
                    <LemonButton type="primary" onClick={handleSendMessage} disabled={!inputValue.trim()}>
                        Send
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
