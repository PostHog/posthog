import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowRight, IconCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Thread } from 'scenes/max/Thread'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { TOOL_DEFINITIONS, ToolRegistration } from 'scenes/max/max-constants'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { MessageTemplate } from 'scenes/max/messages/MessageTemplate'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ProductKey } from '~/queries/schema/schema-general'

import { onboardingLogic } from './onboardingLogic'
import { USE_CASE_OPTIONS } from './productRecommendations'
import { getProductIcon } from './productSelection/ProductSelection'
import { availableOnboardingProducts } from './utils'

const ONBOARDING_TAB_ID = 'onboarding'

const PRODUCT_DESCRIPTIONS: Partial<Record<ProductKey, string>> = {
    [ProductKey.PRODUCT_ANALYTICS]: 'Track events, build funnels, analyze user journeys',
    [ProductKey.SESSION_REPLAY]: 'Watch real user sessions to understand behavior',
    [ProductKey.FEATURE_FLAGS]: 'Control rollouts, target users, kill switches',
    [ProductKey.EXPERIMENTS]: 'A/B tests with statistical significance',
    [ProductKey.SURVEYS]: 'Collect in-app user feedback',
    [ProductKey.ERROR_TRACKING]: 'Catch and debug exceptions automatically',
    [ProductKey.WEB_ANALYTICS]: 'Privacy-friendly website traffic insights',
    [ProductKey.LLM_ANALYTICS]: 'Monitor AI costs, latency, and conversations',
    [ProductKey.DATA_WAREHOUSE]: 'Query all your data in one place',
}

function getProductInfo(
    productKey: ProductKey
): { name: string; description: string; iconKey: string; iconColor: string } | undefined {
    if (!(productKey in availableOnboardingProducts)) {
        return undefined
    }
    const product = availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]
    return {
        name: product.name,
        description: PRODUCT_DESCRIPTIONS[productKey] ?? product.description,
        iconKey: product.icon,
        iconColor: product.iconColor,
    }
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
                    const info = getProductInfo(productKey)
                    if (!info) {
                        return null
                    }
                    const isSelected = selectedProducts.includes(productKey)
                    return (
                        <button
                            key={productKey}
                            onClick={() => onToggleProduct(productKey)}
                            className={clsx(
                                'flex items-center gap-3 p-3 border rounded-lg text-left transition-all cursor-pointer',
                                isSelected
                                    ? 'bg-primary-highlight border-primary ring-1 ring-primary'
                                    : 'bg-surface-primary hover:bg-fill-highlight-100 hover:border-primary'
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ '--index': index } as React.CSSProperties}
                        >
                            <div className="text-2xl">
                                {getProductIcon(info.iconKey, { iconColor: info.iconColor })}
                            </div>
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
                    <LemonButton type="primary" status="alt" onClick={onContinue} sideIcon={<IconArrowRight />}>
                        Continue to setup ({selectedProducts.length} selected)
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

    const threadProps: MaxThreadLogicProps = {
        tabId: ONBOARDING_TAB_ID,
        conversationId: threadLogicKey,
        conversation,
    }

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
                    <div className="flex flex-col min-h-[calc(100vh-var(--scene-layout-header-height))]">
                        <ThreadAutoScroller>
                            {!threadVisible && (
                                <div className="p-3 pt-4 max-w-180 w-full self-center">
                                    <OnboardingWelcome />
                                </div>
                            )}
                            {threadVisible && <Thread className="p-3" />}
                            {recommendedProducts.length > 0 && (
                                <ProductRecommendations
                                    products={recommendedProducts}
                                    selectedProducts={selectedProducts}
                                    onToggleProduct={handleToggleProduct}
                                    onContinue={handleContinueToSetup}
                                />
                            )}
                            <div className="grow" />
                            <SidebarQuestionInput isSticky />
                        </ThreadAutoScroller>
                    </div>
                </AIConsentPopoverWrapper>
            </BindLogic>
        </BindLogic>
    )
}

function OnboardingWelcome(): JSX.Element {
    const { setAgentMode } = useActions(maxThreadLogic)
    const { askMax } = useActions(maxLogic)

    useEffect(() => {
        setAgentMode(AgentMode.Onboarding)
    }, [setAgentMode])

    return (
        <MessageTemplate type="ai">
            <div className="flex flex-col gap-2">
                <p className="mb-0">
                    What are you looking to do? Tell me about your project and I'll recommend the right tools.
                </p>
                <div className="flex flex-col gap-3">
                    {USE_CASE_OPTIONS.map((useCase) => (
                        <button
                            key={useCase.key}
                            onClick={() => askMax(`I want to ${useCase.title.toLowerCase()}`)}
                            className="flex items-center gap-3 p-3 border rounded-lg text-left transition-all cursor-pointer hover:bg-fill-highlight-100 hover:border-primary"
                            data-attr={`onboarding-chat-${useCase.key}`}
                        >
                            <div className="text-2xl">
                                {getProductIcon(useCase.iconKey, { iconColor: useCase.iconColor })}
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="font-semibold">{useCase.title}</div>
                                <div className="text-sm text-muted">{useCase.description}</div>
                            </div>
                            <IconArrowRight className="text-muted shrink-0" />
                        </button>
                    ))}
                </div>
            </div>
        </MessageTemplate>
    )
}
