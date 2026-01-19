import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { ProductKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'

interface OnboardingMessage {
    role: 'assistant' | 'user'
    content: string
    options?: { label: string; value: string }[]
}

const WELCOME_MESSAGES: Record<ProductKey, OnboardingMessage> = {
    product_analytics: {
        role: 'assistant',
        content:
            "Hi! 👋 I'm here to help you get started with Product analytics. I'll guide you through the setup process - you can click the buttons to answer quickly, or just type your response if you prefer to chat.\n\nFirst, let's get PostHog installed. Which platform are you building on?",
        options: [
            { label: 'Web (JavaScript)', value: 'javascript' },
            { label: 'React', value: 'react' },
            { label: 'Next.js', value: 'nextjs' },
            { label: 'Other', value: 'other' },
        ],
    },
    session_replay: {
        role: 'assistant',
        content:
            "Hi! 👋 I'm here to help you set up Session replay. Let's get started!\n\nWhich platform are you using?",
        options: [
            { label: 'Web (JavaScript)', value: 'javascript' },
            { label: 'React', value: 'react' },
            { label: 'Next.js', value: 'nextjs' },
            { label: 'Other', value: 'other' },
        ],
    },
    feature_flags: {
        role: 'assistant',
        content: "Hi! 👋 Let's get Feature flags set up for your project.\n\nWhat platform are you working with?",
        options: [
            { label: 'Web (JavaScript)', value: 'javascript' },
            { label: 'Python', value: 'python' },
            { label: 'Node.js', value: 'nodejs' },
            { label: 'Other', value: 'other' },
        ],
    },
    experiments: {
        role: 'assistant',
        content: "Hi! 👋 Let's set up Experiments for A/B testing.\n\nWhich platform are you using?",
        options: [
            { label: 'Web (JavaScript)', value: 'javascript' },
            { label: 'React', value: 'react' },
            { label: 'Other', value: 'other' },
        ],
    },
    surveys: {
        role: 'assistant',
        content: "Hi! 👋 I'll help you get Surveys set up.\n\nWhich platform are you building on?",
        options: [
            { label: 'Web (JavaScript)', value: 'javascript' },
            { label: 'React', value: 'react' },
            { label: 'Other', value: 'other' },
        ],
    },
    web_analytics: {
        role: 'assistant',
        content: "Hi! 👋 Let's set up Web analytics for your site.\n\nHow would you like to install PostHog?",
        options: [
            { label: 'HTML snippet', value: 'html' },
            { label: 'Next.js', value: 'nextjs' },
            { label: 'Other', value: 'other' },
        ],
    },
    error_tracking: {
        role: 'assistant',
        content: "Hi! 👋 I'll help you set up Error tracking.\n\nWhich platform are you using?",
        options: [
            { label: 'JavaScript', value: 'javascript' },
            { label: 'Python', value: 'python' },
            { label: 'Other', value: 'other' },
        ],
    },
    data_warehouse: {
        role: 'assistant',
        content: "Hi! 👋 Let's connect your Data warehouse.\n\nWhich data source would you like to connect first?",
        options: [
            { label: 'Stripe', value: 'stripe' },
            { label: 'Hubspot', value: 'hubspot' },
            { label: 'Postgres', value: 'postgres' },
            { label: 'Other', value: 'other' },
        ],
    },
    llm_analytics: {
        role: 'assistant',
        content: "Hi! 👋 Let's set up LLM analytics.\n\nWhich LLM provider are you using?",
        options: [
            { label: 'OpenAI', value: 'openai' },
            { label: 'Anthropic', value: 'anthropic' },
            { label: 'LangChain', value: 'langchain' },
            { label: 'Other', value: 'other' },
        ],
    },
}

export function OnboardingChat(): JSX.Element {
    const { productKey } = useValues(onboardingLogic)
    const { completeOnboarding } = useActions(onboardingLogic)
    const [messages, setMessages] = useState<OnboardingMessage[]>([])
    const [inputValue, setInputValue] = useState('')
    const [currentStep, setCurrentStep] = useState(0)

    useEffect(() => {
        if (productKey && WELCOME_MESSAGES[productKey]) {
            setMessages([WELCOME_MESSAGES[productKey]])

            // Track AI chat onboarding started
            window.posthog?.capture('ai chat onboarding started', {
                product_key: productKey,
            })
        }
    }, [productKey])

    const handleOptionClick = (value: string): void => {
        // Add user message
        const userMessage: OnboardingMessage = { role: 'user', content: value }
        setMessages((prev) => [...prev, userMessage])

        // Track interaction
        window.posthog?.capture('ai chat onboarding message sent', {
            step: currentStep,
            message_type: 'button',
            value,
        })

        // Simulate assistant response (in real implementation, this would call the AI)
        setTimeout(() => {
            const assistantMessage: OnboardingMessage = {
                role: 'assistant',
                content: getNextStepMessage(currentStep),
                options: getNextStepOptions(currentStep),
            }
            setMessages((prev) => [...prev, assistantMessage])
            setCurrentStep((prev) => prev + 1)
        }, 500)
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
            step: currentStep,
            message_type: 'chat',
        })

        // Simulate assistant response
        setTimeout(() => {
            const assistantMessage: OnboardingMessage = {
                role: 'assistant',
                content: getNextStepMessage(currentStep),
                options: getNextStepOptions(currentStep),
            }
            setMessages((prev) => [...prev, assistantMessage])
            setCurrentStep((prev) => prev + 1)
        }, 500)
    }

    const handleComplete = (): void => {
        window.posthog?.capture('ai chat onboarding completed', {
            product_key: productKey,
            steps_completed: currentStep,
        })
        completeOnboarding()
    }

    const totalSteps = 4

    return (
        <div className="flex flex-col h-[80vh] max-w-3xl mx-auto">
            {/* Header with progress */}
            <div className="border-b p-4">
                <div className="flex items-center justify-between mb-2">
                    <h2 className="text-xl font-semibold">Getting started with PostHog</h2>
                    <span className="text-sm text-muted">
                        Step {Math.min(currentStep + 1, totalSteps)} of {totalSteps}
                    </span>
                </div>
                <div className="w-full bg-border rounded-full h-2">
                    <div
                        className="bg-primary h-2 rounded-full transition-all"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${(Math.min(currentStep + 1, totalSteps) / totalSteps) * 100}%` }}
                    />
                </div>
            </div>

            {/* Chat messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.map((message, index) => (
                    <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div
                            className={`max-w-[80%] rounded-lg p-3 ${
                                message.role === 'user' ? 'bg-primary text-primary-inverse' : 'bg-bg-light border'
                            }`}
                        >
                            <p className="whitespace-pre-wrap">{message.content}</p>

                            {/* Option buttons */}
                            {message.options && message.role === 'assistant' && index === messages.length - 1 && (
                                <div className="flex flex-wrap gap-2 mt-3">
                                    {message.options.map((option) => (
                                        <LemonButton
                                            key={option.value}
                                            type="secondary"
                                            size="small"
                                            onClick={() => handleOptionClick(option.label)}
                                        >
                                            {option.label}
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
                        placeholder="Type your message or click a button above..."
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

                {currentStep >= totalSteps - 1 && (
                    <div className="mt-4 text-center">
                        <LemonButton type="primary" size="large" onClick={handleComplete}>
                            Complete setup
                        </LemonButton>
                    </div>
                )}
            </div>
        </div>
    )
}

function getNextStepMessage(step: number): string {
    const messages = [
        "Great choice! I've noted that down. Now, let's configure some features.\n\nWould you like to enable autocapture? This automatically tracks clicks, form submissions, and page views without any extra code.",
        'Perfect! Next, would you like to enable session replay? This lets you watch real user sessions to understand how people interact with your product.',
        'Almost done! Would you like to enable AI features? These help you analyze data and get insights faster.',
        "🎉 Awesome! You're all set up! Click 'Complete setup' below to start exploring PostHog.",
    ]
    return messages[Math.min(step, messages.length - 1)]
}

function getNextStepOptions(step: number): { label: string; value: string }[] | undefined {
    const options = [
        [
            { label: 'Yes, enable autocapture', value: 'yes' },
            { label: 'No, I prefer manual tracking', value: 'no' },
        ],
        [
            { label: 'Yes, enable session replay', value: 'yes' },
            { label: 'Not now', value: 'no' },
        ],
        [
            { label: 'Yes, enable AI features', value: 'yes' },
            { label: 'No thanks', value: 'no' },
        ],
        undefined,
    ]
    return options[Math.min(step, options.length - 1)]
}
