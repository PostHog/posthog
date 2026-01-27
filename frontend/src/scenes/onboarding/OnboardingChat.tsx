import './OnboardingChat.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import {
    IconArrowRight,
    IconCheck,
    IconFlag,
    IconFlask,
    IconGraph,
    IconMessage,
    IconRewindPlay,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ProductKey } from '~/queries/schema/schema-general'

import { OnboardingChatMessage, onboardingChatLogic } from './onboardingChatLogic'
import { onboardingLogic } from './onboardingLogic'

interface QuickOption {
    label: string
    description: string
    icon: JSX.Element
    prompt: string
}

const QUICK_OPTIONS: QuickOption[] = [
    {
        label: 'Understand user behavior',
        description: 'Track events, analyze funnels, see how users navigate',
        icon: <IconGraph className="text-warning" />,
        prompt: 'I want to understand how users behave in my product - track events, build funnels, and see user journeys. What tools should I use?',
    },
    {
        label: 'Find and fix issues',
        description: 'Watch session recordings, catch errors',
        icon: <IconRewindPlay className="text-purple" />,
        prompt: 'I want to find and fix issues in my product - watch what users experience and catch errors. What do you recommend?',
    },
    {
        label: 'Run experiments',
        description: 'A/B tests, feature flags, gradual rollouts',
        icon: <IconFlask className="text-danger" />,
        prompt: 'I want to run A/B tests and experiments, use feature flags for gradual rollouts. What should I set up?',
    },
    {
        label: 'Something else',
        description: "I'll describe what I need",
        icon: <IconMessage className="text-primary" />,
        prompt: '', // Empty means show text input
    },
]

const PRODUCT_INFO: Partial<Record<ProductKey, { name: string; description: string; icon: JSX.Element }>> = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        name: 'Product analytics',
        description: 'Track events, build funnels, analyze user journeys',
        icon: <IconGraph className="text-warning" />,
    },
    [ProductKey.SESSION_REPLAY]: {
        name: 'Session replay',
        description: 'Watch real user sessions to understand behavior',
        icon: <IconRewindPlay className="text-purple" />,
    },
    [ProductKey.FEATURE_FLAGS]: {
        name: 'Feature flags',
        description: 'Control rollouts, target users, kill switches',
        icon: <IconFlag className="text-success" />,
    },
    [ProductKey.EXPERIMENTS]: {
        name: 'Experiments',
        description: 'A/B tests with statistical significance',
        icon: <IconFlask className="text-danger" />,
    },
    [ProductKey.SURVEYS]: {
        name: 'Surveys',
        description: 'Collect in-app user feedback',
        icon: <IconMessage className="text-primary" />,
    },
    [ProductKey.ERROR_TRACKING]: {
        name: 'Error tracking',
        description: 'Catch and debug exceptions automatically',
        icon: <IconWarning className="text-danger" />,
    },
    [ProductKey.WEB_ANALYTICS]: {
        name: 'Web analytics',
        description: 'Privacy-friendly website traffic insights',
        icon: <IconGraph className="text-primary" />,
    },
    [ProductKey.LLM_ANALYTICS]: {
        name: 'LLM observability',
        description: 'Monitor AI costs, latency, and conversations',
        icon: <IconGraph className="text-purple" />,
    },
    [ProductKey.DATA_WAREHOUSE]: {
        name: 'Data warehouse',
        description: 'Query all your data in one place',
        icon: <IconGraph className="text-muted" />,
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
    const { messages, isStreaming, recommendedProducts, selectedProducts, hasRecommendations } =
        useValues(onboardingChatLogic)
    const { sendMessage, toggleSelectedProduct } = useActions(onboardingChatLogic)
    const { setProductKey } = useActions(onboardingLogic)

    const [inputValue, setInputValue] = useState('')
    const [showOptions, setShowOptions] = useState(true)
    const [showSetupButton, setShowSetupButton] = useState(false)

    const sentinelRef = useRef<HTMLDivElement>(null)
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
    }, [messages, isStreaming])

    // Show setup button when we have recommendations
    useEffect(() => {
        if (hasRecommendations && !isStreaming) {
            setShowSetupButton(true)
        }
    }, [hasRecommendations, isStreaming])

    const handleOptionClick = (option: QuickOption): void => {
        setShowOptions(false)

        window.posthog?.capture('ai chat onboarding option clicked', {
            option_label: option.label,
        })

        if (option.prompt) {
            // Send the pre-defined prompt to the AI
            sendMessage(option.prompt)
        } else {
            // "Something else" - focus the input
            inputRef.current?.focus()
        }
    }

    const handleSendMessage = (): void => {
        if (!inputValue.trim() || isStreaming) {
            return
        }

        setShowOptions(false)
        sendMessage(inputValue.trim())
        setInputValue('')
        setShowSetupButton(false)
    }

    const handleContinueToSetup = (): void => {
        if (selectedProducts.length > 0) {
            window.posthog?.capture('ai chat onboarding discovery complete', {
                products_selected: selectedProducts,
                products_recommended: recommendedProducts,
            })
            // Set the first selected product to trigger onboarding flow
            setProductKey(selectedProducts[0])
        }
    }

    return (
        <div className="OnboardingChat flex flex-col h-full min-h-[600px]">
            {/* Messages area */}
            <div className="flex-1 overflow-y-auto">
                <div className="flex flex-col items-stretch w-full max-w-200 self-center gap-2 mx-auto p-4 pb-0">
                    {messages.map((message: OnboardingChatMessage) => (
                        <div
                            key={message.id}
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
                                                : 'bg-surface-primary',
                                            message.status === 'loading' && 'animate-pulse'
                                        )}
                                    >
                                        {message.content ? (
                                            <LemonMarkdown>{message.content}</LemonMarkdown>
                                        ) : message.status === 'loading' ? (
                                            <div className="flex gap-1">
                                                <span className="OnboardingChat__typing-dot w-2 h-2 bg-muted rounded-full" />
                                                <span className="OnboardingChat__typing-dot w-2 h-2 bg-muted rounded-full" />
                                                <span className="OnboardingChat__typing-dot w-2 h-2 bg-muted rounded-full" />
                                            </div>
                                        ) : null}
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))}

                    {/* Quick options - shown initially */}
                    {showOptions && messages.length === 1 && (
                        <div className="OnboardingChat__message relative flex mr-10 animate-fade-in">
                            <div className="flex flex-wrap gap-2 mt-3 w-full">
                                {QUICK_OPTIONS.map((option, index) => (
                                    <button
                                        key={option.label}
                                        onClick={() => handleOptionClick(option)}
                                        className="OnboardingChat__option flex items-center gap-2 px-4 py-2.5 border rounded-lg bg-surface-primary hover:bg-fill-highlight-100 hover:border-primary transition-all text-left"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{ '--index': index } as React.CSSProperties}
                                    >
                                        <span className="text-lg">{option.icon}</span>
                                        <div>
                                            <div className="font-medium">{option.label}</div>
                                            <div className="text-xs text-muted">{option.description}</div>
                                        </div>
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Product recommendations */}
                    {hasRecommendations && !isStreaming && (
                        <div className="OnboardingChat__message relative flex mr-10 animate-fade-in">
                            <div className="flex flex-col gap-px w-full break-words items-start">
                                <div className="flex flex-col gap-2 mt-3 w-full">
                                    <div className="text-sm font-medium text-muted mb-1">
                                        Recommended for you (click to select):
                                    </div>
                                    {recommendedProducts.map((productKey: ProductKey, index: number) => {
                                        const info = PRODUCT_INFO[productKey]
                                        if (!info) {
                                            return null
                                        }
                                        const isSelected = selectedProducts.includes(productKey)
                                        return (
                                            <button
                                                key={productKey}
                                                onClick={() => toggleSelectedProduct(productKey)}
                                                className={clsx(
                                                    'OnboardingChat__option flex items-center gap-3 p-3 border rounded-lg text-left transition-all',
                                                    isSelected
                                                        ? 'bg-primary-highlight border-primary ring-1 ring-primary'
                                                        : 'bg-surface-primary hover:bg-fill-highlight-100 hover:border-primary'
                                                )}
                                                // eslint-disable-next-line react/forbid-dom-props
                                                style={{ '--index': index } as React.CSSProperties}
                                            >
                                                <div className="text-2xl">{info.icon}</div>
                                                <div className="flex-1">
                                                    <div className="font-semibold">{info.name}</div>
                                                    <div className="text-sm text-muted">{info.description}</div>
                                                </div>
                                                {isSelected && (
                                                    <div className="text-primary">
                                                        <IconCheck className="text-xl" />
                                                    </div>
                                                )}
                                            </button>
                                        )
                                    })}
                                </div>

                                {showSetupButton && selectedProducts.length > 0 && (
                                    <div className="mt-4">
                                        <LemonButton type="primary" size="large" onClick={handleContinueToSetup}>
                                            Continue to setup ({selectedProducts.length} selected)
                                            <IconArrowRight className="ml-2" />
                                        </LemonButton>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

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
                                if (inputValue.trim() && !isStreaming) {
                                    handleSendMessage()
                                }
                            }}
                            disabled={isStreaming}
                        />
                        <div className="absolute bottom-2 right-2">
                            <LemonButton
                                type={inputValue.trim() ? 'primary' : 'secondary'}
                                size="small"
                                onClick={handleSendMessage}
                                disabled={!inputValue.trim() || isStreaming}
                                loading={isStreaming}
                                icon={<IconArrowRight />}
                            />
                        </div>
                    </div>
                </div>
                <div className="text-center text-xs text-muted mt-2">
                    Press Enter to send • AI-powered recommendations
                </div>
            </div>
        </div>
    )
}
