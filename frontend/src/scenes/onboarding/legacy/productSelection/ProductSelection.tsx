import { useActions, useValues } from 'kea'

import { IconArrowRight, IconChevronDown, IconCursor } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { availableOnboardingProducts, getProductIcon } from 'scenes/onboarding/shared/utils'

import { ProductKey } from '~/queries/schema/schema-general'

import { OnboardingExitAction } from '../exit'
import { UseCaseDefinition } from '../productRecommendations'
import { productSelectionLogic } from './productSelectionLogic'

type AvailableOnboardingProductKey = keyof typeof availableOnboardingProducts

const isAvailableOnboardingProductKey = (key: string | ProductKey): key is AvailableOnboardingProductKey =>
    key in availableOnboardingProducts

function BrowsingHistoryBanner(): JSX.Element | null {
    const { hasBrowsingHistory, browsingHistoryLabels } = useValues(productSelectionLogic)

    if (!hasBrowsingHistory) {
        return null
    }

    return (
        <LemonBanner type="info" className="mb-6">
            Based on the documentation you browsed on our website ({browsingHistoryLabels.slice(0, 3).join(', ')}),
            we've tailored recommendations to your interests.
        </LemonBanner>
    )
}

function ChoosePathStep(): JSX.Element {
    const { useCases } = useValues(productSelectionLogic)
    const { selectUseCase, selectPickMyself } = useActions(productSelectionLogic)

    const headingCopy = getFeatureFlagPayload('onboarding-product-selection-heading') as
        | { heading?: string; subheading?: string }
        | undefined
    const heading = headingCopy?.heading ?? 'What do you want to do with PostHog?'
    const subheading = headingCopy?.subheading ?? 'Pick a goal to get started with the right tools'

    return (
        <div className="max-w-6xl w-full">
            <h1 className="text-2xl font-bold text-center mb-2">{heading}</h1>
            <p className="text-center text-muted mb-6">{subheading}</p>

            {/* Use cases grid - responsive: 1 col on mobile, 2 on small, 3 on medium+ */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 sm:gap-4">
                {useCases.map((useCase: UseCaseDefinition) => (
                    <LemonCard
                        key={useCase.key}
                        className="OnboardingProductCard p-3 cursor-pointer"
                        onClick={() => selectUseCase(useCase.key)}
                        hoverEffect
                        data-attr={`use-case-${useCase.key}`}
                    >
                        <div className="flex flex-col items-center text-center gap-2">
                            <div className="text-2xl">
                                {getProductIcon(useCase.iconKey, {
                                    iconColor: useCase.iconColor,
                                    className: 'text-2xl',
                                })}
                            </div>
                            <div>
                                <div className="font-semibold mb-1">{useCase.title}</div>
                                <p className="text-muted text-sm mb-0">{useCase.description}</p>
                            </div>
                        </div>
                    </LemonCard>
                ))}

                {/* Pick myself option */}
                <LemonCard
                    className="OnboardingProductCard p-3 cursor-pointer"
                    onClick={() => selectPickMyself()}
                    hoverEffect
                    data-attr="pick-myself-card"
                >
                    <div className="flex flex-col items-center text-center gap-2">
                        <div className="text-2xl">
                            <IconCursor className="text-2xl" color="rgb(100, 116, 139)" />
                        </div>
                        <div>
                            <div className="font-semibold mb-1">I'll pick myself</div>
                            <p className="text-muted text-sm mb-0">I know exactly which tools I need</p>
                        </div>
                    </div>
                </LemonCard>
            </div>
        </div>
    )
}

function ProductCard({
    productKey,
    selected,
    onToggle,
}: {
    productKey: AvailableOnboardingProductKey
    selected: boolean
    onToggle: () => void
}): JSX.Element {
    const product = availableOnboardingProducts[productKey]

    return (
        <LemonCard
            data-attr={`${productKey}-onboarding-card`}
            className="OnboardingProductCard relative cursor-pointer hover:transform-none p-4"
            onClick={onToggle}
            focused={selected}
            hoverEffect
        >
            <div className="flex flex-col items-center text-center gap-2">
                <div className="text-2xl">
                    {getProductIcon(product.icon, {
                        iconColor: product.iconColor,
                        className: 'text-2xl',
                    })}
                </div>
                <div>
                    <h3 className="font-semibold mb-1 text-sm">{product.name}</h3>
                    <p className="text-muted text-xs mb-0">{product.description}</p>
                </div>
            </div>
        </LemonCard>
    )
}

function ProductSelectionStep(): JSX.Element {
    const {
        selectedProducts,
        firstProductOnboarding,
        recommendedProducts,
        otherProducts,
        showAllProducts,
        canContinue,
        recommendationSourceLabel,
        recommendationSource,
    } = useValues(productSelectionLogic)
    const { toggleProduct, setFirstProductOnboarding, handleStartOnboarding, setShowAllProducts } =
        useActions(productSelectionLogic)

    const availableRecommendedProducts = recommendedProducts.filter(isAvailableOnboardingProductKey)
    const availableOtherProducts = otherProducts.filter(isAvailableOnboardingProductKey)

    return (
        <div className="max-w-6xl w-full">
            <h1 className="text-2xl font-bold text-center mb-2">Which tools would you like to use?</h1>
            <p className="text-center text-muted mb-8">
                {recommendationSourceLabel ? (
                    <>We've pre-selected some tools {recommendationSourceLabel}. Feel free to change or add more.</>
                ) : (
                    <>Select all that apply, you can pick more than one!</>
                )}
            </p>

            {/* Browsing history banner */}
            {recommendationSource === 'browsing_history' && <BrowsingHistoryBanner />}

            {/* Tools list */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 justify-center w-full">
                {availableRecommendedProducts.map((productKey) => (
                    <ProductCard
                        key={productKey}
                        productKey={productKey}
                        selected={selectedProducts.includes(productKey)}
                        onToggle={() => toggleProduct(productKey)}
                    />
                ))}

                {availableOtherProducts.length > 0 &&
                    showAllProducts &&
                    availableOtherProducts.map((productKey) => (
                        <ProductCard
                            key={productKey}
                            productKey={productKey}
                            selected={selectedProducts.includes(productKey)}
                            onToggle={() => toggleProduct(productKey)}
                        />
                    ))}
            </div>

            {availableOtherProducts.length > 0 && availableRecommendedProducts.length > 0 && !showAllProducts && (
                <div className="flex justify-center mt-4">
                    <button
                        onClick={() => setShowAllProducts(true)}
                        className="text-muted hover:text-default text-sm flex items-center gap-1 cursor-pointer"
                    >
                        Show all products ({availableOtherProducts.length} more) <IconChevronDown className="text-xs" />
                    </button>
                </div>
            )}

            <div className="flex flex-col items-center gap-4 mt-8">
                {selectedProducts.length > 1 ? (
                    <div className="flex flex-col sm:flex-row gap-2 items-center justify-center w-full">
                        <LemonLabel>Start with</LemonLabel>
                        <LemonSelect
                            value={firstProductOnboarding}
                            options={selectedProducts.filter(isAvailableOnboardingProductKey).map((productKey) => ({
                                label: availableOnboardingProducts[productKey].name,
                                value: productKey,
                            }))}
                            onChange={(value) => value && setFirstProductOnboarding(value)}
                            placeholder="Select a product"
                            className="bg-surface-primary"
                        />
                        <LemonButton
                            sideIcon={<IconArrowRight />}
                            onClick={handleStartOnboarding}
                            type="primary"
                            status="alt"
                            data-attr="onboarding-continue"
                        >
                            Go
                        </LemonButton>
                    </div>
                ) : (
                    <LemonButton
                        type="primary"
                        status="alt"
                        onClick={handleStartOnboarding}
                        data-attr="onboarding-continue"
                        sideIcon={<IconArrowRight />}
                        disabledReason={!canContinue ? 'Select at least one product to continue' : undefined}
                    >
                        Get started
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

export function ProductSelection(): JSX.Element {
    const { currentStep } = useValues(productSelectionLogic)

    return (
        // The onboarding card (LegacyOnboarding) owns the background, padding, and centering; this
        // wrapper stays transparent so its gray shows through and just lays out the step content.
        <div className="flex flex-col items-center w-full overflow-x-hidden">
            {currentStep === 'choose_path' && <ChoosePathStep />}
            {currentStep === 'product_selection' && <ProductSelectionStep />}
            {currentStep === 'choose_path' && <OnboardingExitAction />}
        </div>
    )
}
