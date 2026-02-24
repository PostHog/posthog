import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

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
import { LemonButton } from '@posthog/lemon-ui'

import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { TOOL_DEFINITIONS, ToolRegistration } from 'scenes/max/max-constants'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { MessageTemplate } from 'scenes/max/messages/MessageTemplate'
import { Thread } from 'scenes/max/Thread'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ProductKey } from '~/queries/schema/schema-general'

import { onboardingLogic } from './onboardingLogic'

const ONBOARDING_TAB_ID = 'onboarding'

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

// Map from tool product keys to PostHog ProductKey enum
const TOOL_PRODUCT_TO_PRODUCT_KEY: Record<string, ProductKey> = {
    product_analytics: ProductKey.PRODUCT_ANALYTICS,
    session_replay: ProductKey.SESSION_REPLAY,
    feature_flags: ProductKey.FEATURE_FLAGS,
    experiments: ProductKey.EXPERIMENTS,
    surveys: ProductKey.SURVEYS,
    web_analytics: ProductKey.WEB_ANALYTICS,
    error_tracking: ProductKey.ERROR_TRACKING,
    data_warehouse: ProductKey.DATA_WAREHOUSE,
    llm_observability: ProductKey.LLM_ANALYTICS,
}

interface ProductRecommendationsProps {
    products: ProductKey[]
    selectedProducts: ProductKey[]
    onToggleProduct: (product: ProductKey) => void
    onContinue: () => void
}

function ProductRecommendations({
    products,
    selectedProducts,
    onToggleProduct,
    onContinue,
}: ProductRecommendationsProps): JSX.Element {
    return (
        <div className="flex flex-col w-full max-w-180 self-center break-words items-start p-3">
            <div className="flex flex-col gap-3 mt-3 w-full">
                <div className="text-sm font-medium text-muted mb-1">Recommended for you (click to select):</div>
                {products.map((productKey: ProductKey, index: number) => {
                    const info = PRODUCT_INFO[productKey]
                    if (!info) {
                        return null
                    }
                    const isSelected = selectedProducts.includes(productKey)
                    return (
                        <button
                            key={productKey}
                            onClick={() => onToggleProduct(productKey)}
                            className={clsx(
                                'flex items-center gap-3 p-3 border rounded-lg text-left transition-all',
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

            {selectedProducts.length > 0 && (
                <div className="mt-4">
                    <LemonButton type="primary" size="large" onClick={onContinue}>
                        Continue to setup ({selectedProducts.length} selected)
                        <IconArrowRight className="ml-2" />
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function OnboardingMax(): JSX.Element {
    const { setProductKey } = useActions(onboardingLogic)
    const { registerTool, deregisterTool } = useActions(maxGlobalLogic)

    const [recommendedProducts, setRecommendedProducts] = useState<ProductKey[]>([])
    const [selectedProducts, setSelectedProducts] = useState<ProductKey[]>([])

    const { threadVisible, conversation, threadLogicKey } = useValues(maxLogic({ tabId: ONBOARDING_TAB_ID }))

    const threadProps: MaxThreadLogicProps = useMemo(
        () => ({
            tabId: ONBOARDING_TAB_ID,
            conversationId: threadLogicKey,
            conversation,
        }),
        [threadLogicKey, conversation]
    )

    // Register the recommend_products tool callback
    useEffect(() => {
        const toolRegistration: ToolRegistration = {
            identifier: 'recommend_products',
            name: TOOL_DEFINITIONS['recommend_products'].name,
            description: TOOL_DEFINITIONS['recommend_products'].description,
            callback: (toolOutput: { products?: string[] }) => {
                if (toolOutput?.products && Array.isArray(toolOutput.products)) {
                    const products = toolOutput.products
                        .map((product: string) => TOOL_PRODUCT_TO_PRODUCT_KEY[product])
                        .filter((key: ProductKey | undefined): key is ProductKey => key !== undefined)

                    if (products.length > 0) {
                        setRecommendedProducts(products)
                        setSelectedProducts(products) // Pre-select all recommended products
                    }
                }
            },
        }
        registerTool(toolRegistration)

        return () => {
            deregisterTool('recommend_products')
        }
    }, [registerTool, deregisterTool])

    // Set agent mode to Onboarding when the thread logic mounts
    useEffect(() => {
        const logic = maxThreadLogic.findMounted(threadProps)
        if (logic) {
            logic.actions.setAgentMode(AgentMode.Onboarding)
        }
    }, [threadProps])

    const handleToggleProduct = (product: ProductKey): void => {
        setSelectedProducts((prev) => (prev.includes(product) ? prev.filter((p) => p !== product) : [...prev, product]))
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
        <BindLogic logic={maxLogic} props={{ tabId: ONBOARDING_TAB_ID }}>
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <AIConsentPopoverWrapper>
                    <div className="flex flex-col h-full min-h-[calc(100vh-var(--scene-layout-header-height))]">
                        {!threadVisible ? (
                            <div className="flex flex-col flex-1 justify-center items-center px-3">
                                <OnboardingWelcome />
                            </div>
                        ) : (
                            <ThreadAutoScroller>
                                <Thread className="p-3" />
                                {recommendedProducts.length > 0 && (
                                    <ProductRecommendations
                                        products={recommendedProducts}
                                        selectedProducts={selectedProducts}
                                        onToggleProduct={handleToggleProduct}
                                        onContinue={handleContinueToSetup}
                                    />
                                )}
                                <SidebarQuestionInput isSticky />
                            </ThreadAutoScroller>
                        )}
                    </div>
                </AIConsentPopoverWrapper>
            </BindLogic>
        </BindLogic>
    )
}

function OnboardingWelcome(): JSX.Element {
    const { setAgentMode } = useActions(maxThreadLogic)
    const { askMax } = useActions(maxLogic({ tabId: ONBOARDING_TAB_ID }))

    useEffect(() => {
        setAgentMode(AgentMode.Onboarding)
    }, [setAgentMode])

    return (
        <div className="flex flex-col items-stretch w-full max-w-180 gap-4">
            <MessageTemplate type="ai" className="items-stretch" wrapperClassName="w-full">
                <div className="flex flex-col gap-3">
                    <div className="text-center">
                        <div className="font-bold text-base mb-1">
                            What are you building and what do you need help with?
                        </div>
                        <div className="text-sm text-muted">
                            I'll recommend the best PostHog products for your needs. Pick an option or describe what you
                            need:
                        </div>
                    </div>
                    <div className="flex flex-col gap-2">
                        {QUICK_OPTIONS.map((option) => (
                            <button
                                key={option.label}
                                onClick={() => askMax(option.prompt)}
                                className="flex items-center gap-3 p-3 border rounded-lg text-left transition-all hover:bg-fill-highlight-100 hover:border-primary"
                            >
                                <div className="text-2xl">{option.icon}</div>
                                <div className="flex-1">
                                    <div className="font-semibold">{option.label}</div>
                                    <div className="text-sm text-muted">{option.description}</div>
                                </div>
                                <IconArrowRight className="text-muted" />
                            </button>
                        ))}
                    </div>
                </div>
            </MessageTemplate>
            <SidebarQuestionInput />
        </div>
    )
}
