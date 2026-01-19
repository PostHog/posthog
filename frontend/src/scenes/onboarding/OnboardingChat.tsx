import './OnboardingChat.scss'

import clsx from 'clsx'
import { useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'

import {
    IconArrowRight,
    IconChartLine,
    IconFlag,
    IconFlask,
    IconMessage,
    IconRewindPlay,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ProductKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'

interface OnboardingOption {
    label: string
    value: string
    description?: string
    icon?: JSX.Element
    products?: ProductKey[]
}

interface OnboardingMessage {
    role: 'assistant' | 'user'
    content: string
    options?: OnboardingOption[]
}

const PRODUCT_INFO: Record<ProductKey, { name: string; description: string; icon: JSX.Element }> = {
    product_analytics: {
        name: 'Product analytics',
        description: 'Track events, build funnels, analyze user journeys',
        icon: <IconChartLine className="text-warning" />,
    },
    session_replay: {
        name: 'Session replay',
        description: 'Watch real user sessions to understand behavior',
        icon: <IconRewindPlay className="text-purple" />,
    },
    feature_flags: {
        name: 'Feature flags',
        description: 'Control rollouts, target users, kill switches',
        icon: <IconFlag className="text-success" />,
    },
    experiments: {
        name: 'Experiments',
        description: 'A/B tests with statistical significance',
        icon: <IconFlask className="text-danger" />,
    },
    surveys: {
        name: 'Surveys',
        description: 'Collect in-app user feedback',
        icon: <IconMessage className="text-primary" />,
    },
    error_tracking: {
        name: 'Error tracking',
        description: 'Catch and debug exceptions automatically',
        icon: <IconWarning className="text-danger" />,
    },
    web_analytics: {
        name: 'Web analytics',
        description: 'Privacy-friendly website traffic insights',
        icon: <IconChartLine className="text-primary" />,
    },
    llm_analytics: {
        name: 'LLM observability',
        description: 'Monitor AI costs, latency, and conversations',
        icon: <IconChartLine className="text-purple" />,
    },
    data_warehouse: {
        name: 'Data warehouse',
        description: 'Query all your data in one place',
        icon: <IconChartLine className="text-muted" />,
    },
}

const INITIAL_MESSAGE: OnboardingMessage = {
    role: 'assistant',
    content: "Hi! I'm here to help you get the most out of PostHog. **What's your main goal right now?**",
    options: [
        {
            label: 'Understand user behavior',
            value: 'understand_users',
            description: 'Track events, analyze funnels, see how users navigate',
            icon: <IconChartLine />,
        },
        {
            label: 'Find and fix issues',
            value: 'fix_issues',
            description: 'Watch session recordings, catch errors',
            icon: <IconRewindPlay />,
        },
        {
            label: 'Run experiments',
            value: 'experiments',
            description: 'A/B tests, feature flags, gradual rollouts',
            icon: <IconFlask />,
        },
        {
            label: 'Something else',
            value: 'other',
            description: "I'll explain what I need",
            icon: <IconMessage />,
        },
    ],
}

const GOAL_RESPONSES: Record<string, OnboardingMessage> = {
    understand_users: {
        role: 'assistant',
        content:
            'Great choice! To understand user behavior, I recommend starting with **Product analytics**. You can also add **Session replay** to watch exactly what users do.\n\nWhich would you like to set up?',
        options: [
            {
                label: 'Both - Analytics + Replay',
                value: 'analytics_and_replay',
                description: 'Most popular combination',
                products: ['product_analytics', 'session_replay'],
            },
            {
                label: 'Just Product analytics',
                value: 'analytics_only',
                products: ['product_analytics'],
            },
            {
                label: 'Just Session replay',
                value: 'replay_only',
                products: ['session_replay'],
            },
        ],
    },
    fix_issues: {
        role: 'assistant',
        content:
            'Perfect for debugging! **Session replay** lets you watch exactly what users experienced, and **Error tracking** automatically catches exceptions.\n\nWhich would you like?',
        options: [
            {
                label: 'Both - Replay + Error tracking',
                value: 'replay_and_errors',
                description: 'Full debugging toolkit',
                products: ['session_replay', 'error_tracking'],
            },
            {
                label: 'Just Session replay',
                value: 'replay_only',
                products: ['session_replay'],
            },
            {
                label: 'Just Error tracking',
                value: 'errors_only',
                products: ['error_tracking'],
            },
        ],
    },
    experiments: {
        role: 'assistant',
        content:
            'For experimentation, **Feature flags** let you control who sees what, and **Experiments** adds A/B testing with statistical analysis.\n\nWhat would you like to set up?',
        options: [
            {
                label: 'Both - Flags + Experiments',
                value: 'flags_and_experiments',
                description: 'Full experimentation platform',
                products: ['feature_flags', 'experiments'],
            },
            {
                label: 'Just Feature flags',
                value: 'flags_only',
                products: ['feature_flags'],
            },
        ],
    },
    other: {
        role: 'assistant',
        content: 'No problem! What are you trying to accomplish?',
        options: [
            {
                label: 'Collect user feedback',
                value: 'feedback',
                icon: <IconMessage />,
            },
            {
                label: 'Website analytics',
                value: 'web_analytics',
                icon: <IconChartLine />,
            },
            {
                label: 'Monitor AI/LLM app',
                value: 'llm',
                icon: <IconChartLine />,
            },
        ],
    },
    feedback: {
        role: 'assistant',
        content:
            "**Surveys** lets you collect in-app feedback at the perfect moment - after a purchase, when someone's about to churn, or just to understand sentiment.",
        options: [
            {
                label: 'Set up Surveys',
                value: 'setup_surveys',
                products: ['surveys'],
            },
            {
                label: 'Add Session replay too',
                value: 'surveys_and_replay',
                description: 'See what users do before responding',
                products: ['surveys', 'session_replay'],
            },
        ],
    },
    web_analytics: {
        role: 'assistant',
        content:
            '**Web analytics** gives you privacy-friendly, cookieless website traffic insights - pageviews, referrers, top pages. A simpler Google Analytics alternative.',
        options: [
            {
                label: 'Set up Web analytics',
                value: 'setup_web_analytics',
                products: ['web_analytics'],
            },
            {
                label: 'Add Product analytics too',
                value: 'web_and_product',
                description: 'For deeper user behavior insights',
                products: ['web_analytics', 'product_analytics'],
            },
        ],
    },
    llm: {
        role: 'assistant',
        content:
            '**LLM observability** helps you monitor your AI application - track costs, latency, token usage, and analyze conversations.',
        options: [
            {
                label: 'Set up LLM observability',
                value: 'setup_llm',
                products: ['llm_analytics'],
            },
        ],
    },
}

function getScrollableContainer(element: HTMLElement | null): HTMLElement | null {
    if (!element) {
        return null
    }
    let parent = element.parentElement
    while (parent) {
        const { overflow, overflowY } = window.getComputedStyle(parent)
        if (overflow === 'auto' || overflow === 'scroll' || overflowY === 'auto' || overflowY === 'scroll') {
            return parent
        }
        parent = parent.parentElement
    }
    return document.documentElement
}

export function OnboardingChat(): JSX.Element {
    const { setProductKey, completeOnboarding } = useActions(onboardingLogic)
    const [messages, setMessages] = useState<OnboardingMessage[]>([INITIAL_MESSAGE])
    const [inputValue, setInputValue] = useState('')
    const [selectedProducts, setSelectedProducts] = useState<ProductKey[]>([])
    const [isTyping, setIsTyping] = useState(false)

    const sentinelRef = useRef<HTMLDivElement>(null)
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLTextAreaElement>(null)

    // Auto-scroll when messages change
    useEffect(() => {
        if (sentinelRef.current) {
            const scrollableContainer = getScrollableContainer(sentinelRef.current)
            if (scrollableContainer) {
                requestAnimationFrame(() => {
                    scrollableContainer.scrollTo({
                        top: scrollableContainer.scrollHeight,
                        behavior: 'smooth',
                    })
                })
            }
        }
    }, [messages, isTyping])

    useEffect(() => {
        window.posthog?.capture('ai chat onboarding started')
    }, [])

    const addAssistantMessage = (message: OnboardingMessage): void => {
        setIsTyping(true)
        setTimeout(() => {
            setIsTyping(false)
            setMessages((prev) => [...prev, message])
        }, 600)
    }

    const handleOptionClick = (option: OnboardingOption): void => {
        const userMessage: OnboardingMessage = { role: 'user', content: option.label }
        setMessages((prev) => [...prev, userMessage])

        window.posthog?.capture('ai chat onboarding option clicked', {
            option_value: option.value,
            option_label: option.label,
        })

        // If this option has products, go to setup
        if (option.products && option.products.length > 0) {
            setSelectedProducts(option.products)
            if (option.products[0]) {
                setProductKey(option.products[0])
            }

            addAssistantMessage({
                role: 'assistant',
                content: `Great! I'll help you set up ${option.products.length > 1 ? 'these products' : PRODUCT_INFO[option.products[0]]?.name || 'this product'}.\n\nHere's what you're getting:`,
                options: [
                    {
                        label: 'Continue to setup',
                        value: 'continue_setup',
                    },
                ],
            })
            return
        }

        // Handle follow-up questions
        if (GOAL_RESPONSES[option.value]) {
            addAssistantMessage(GOAL_RESPONSES[option.value])
            return
        }

        // Handle setup continuation
        if (option.value === 'continue_setup') {
            handleComplete()
        }
    }

    const handleSendMessage = (): void => {
        if (!inputValue.trim()) {
            return
        }

        const userMessage: OnboardingMessage = { role: 'user', content: inputValue }
        setMessages((prev) => [...prev, userMessage])
        setInputValue('')

        window.posthog?.capture('ai chat onboarding message sent', {
            message_type: 'text',
        })

        addAssistantMessage({
            role: 'assistant',
            content: "Thanks for sharing! Based on what you've described, what sounds most relevant?",
            options: INITIAL_MESSAGE.options,
        })
    }

    const handleComplete = (): void => {
        window.posthog?.capture('ai chat onboarding completed', {
            products_selected: selectedProducts,
        })
        completeOnboarding()
    }

    return (
        <div className="OnboardingChat flex flex-col h-full min-h-[600px]">
            {/* Messages area */}
            <div className="flex-1 overflow-y-auto">
                <div className="flex flex-col items-stretch w-full max-w-200 self-center gap-2 mx-auto p-4 pb-0">
                    {messages.map((message, index) => (
                        <div
                            key={index}
                            className={clsx(
                                'OnboardingChat__message relative flex animate-fade-in',
                                message.role === 'user' ? 'flex-row-reverse ml-10' : 'mr-10'
                            )}
                        >
                            <div
                                className={clsx(
                                    'flex flex-col gap-px w-full break-words',
                                    message.role === 'user' ? 'items-end' : 'items-start'
                                )}
                            >
                                <div className="max-w-full">
                                    <div
                                        className={clsx(
                                            'border py-3 px-4 rounded-lg',
                                            message.role === 'user'
                                                ? 'bg-fill-highlight-100 font-medium'
                                                : 'bg-surface-primary'
                                        )}
                                    >
                                        <LemonMarkdown>{message.content}</LemonMarkdown>
                                    </div>

                                    {/* Product cards for selected products */}
                                    {message.role === 'assistant' &&
                                        index === messages.length - 1 &&
                                        selectedProducts.length > 0 && (
                                            <div className="flex flex-col gap-2 mt-3">
                                                {selectedProducts.map((productKey) => {
                                                    const info = PRODUCT_INFO[productKey]
                                                    if (!info) {
                                                        return null
                                                    }
                                                    return (
                                                        <div
                                                            key={productKey}
                                                            className="flex items-center gap-3 p-3 border rounded-lg bg-surface-primary"
                                                        >
                                                            <div className="text-2xl">{info.icon}</div>
                                                            <div>
                                                                <div className="font-semibold">{info.name}</div>
                                                                <div className="text-sm text-muted">
                                                                    {info.description}
                                                                </div>
                                                            </div>
                                                        </div>
                                                    )
                                                })}
                                            </div>
                                        )}

                                    {/* Option buttons */}
                                    {message.options &&
                                        message.role === 'assistant' &&
                                        index === messages.length - 1 && (
                                            <div className="flex flex-wrap gap-2 mt-3">
                                                {message.options.map((option, optionIndex) => (
                                                    <button
                                                        key={option.value}
                                                        onClick={() => handleOptionClick(option)}
                                                        className="OnboardingChat__option flex items-center gap-2 px-4 py-2.5 border rounded-lg bg-surface-primary hover:bg-fill-highlight-100 hover:border-primary transition-all text-left"
                                                        // eslint-disable-next-line react/forbid-dom-props
                                                        style={{ '--index': optionIndex } as React.CSSProperties}
                                                    >
                                                        {option.icon && (
                                                            <span className="text-muted">{option.icon}</span>
                                                        )}
                                                        <div>
                                                            <div className="font-medium">{option.label}</div>
                                                            {option.description && (
                                                                <div className="text-xs text-muted">
                                                                    {option.description}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                </div>
                            </div>
                        </div>
                    ))}

                    {/* Typing indicator */}
                    {isTyping && (
                        <div className="OnboardingChat__message relative flex mr-10 animate-fade-in">
                            <div className="border py-3 px-4 rounded-lg bg-surface-primary">
                                <div className="flex gap-1">
                                    <span className="OnboardingChat__typing-dot w-2 h-2 bg-muted rounded-full" />
                                    <span className="OnboardingChat__typing-dot w-2 h-2 bg-muted rounded-full" />
                                    <span className="OnboardingChat__typing-dot w-2 h-2 bg-muted rounded-full" />
                                </div>
                            </div>
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                    <div ref={sentinelRef} className="h-0 pointer-events-none" />
                </div>
            </div>

            {/* Input area - sticky at bottom */}
            <div className="sticky bottom-0 z-10 w-full max-w-200 self-center mx-auto p-4">
                <div className="border border-primary rounded-lg backdrop-blur-sm bg-glass-bg-3000">
                    <div className="relative">
                        <LemonTextArea
                            ref={inputRef}
                            value={inputValue}
                            onChange={(value) => setInputValue(value)}
                            placeholder="Or describe what you're building..."
                            minRows={1}
                            maxRows={4}
                            className="!border-none !bg-transparent min-h-12 py-3 pl-4 pr-14 resize-none"
                            onPressEnter={() => {
                                if (inputValue.trim()) {
                                    handleSendMessage()
                                }
                            }}
                        />
                        <div className="absolute bottom-2 right-2">
                            <LemonButton
                                type={inputValue.trim() ? 'primary' : 'secondary'}
                                size="small"
                                onClick={handleSendMessage}
                                disabled={!inputValue.trim()}
                                icon={<IconArrowRight />}
                            />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
