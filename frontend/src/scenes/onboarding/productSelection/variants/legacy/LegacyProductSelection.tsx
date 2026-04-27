import { useActions, useValues } from 'kea'

import { IconArrowRight, IconChevronDown, IconCursor } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand/Logomark'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { OnboardingExitAction } from '../../../exit'
import { UseCaseDefinition } from '../../../productRecommendations'
import { availableOnboardingProducts, getProductIcon } from '../../../utils'
import { productSelectionLogic } from '../../productSelectionLogic'

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
    const subheading = headingCopy?.subheading ?? 'Pick a goal to get started with the right products'

    return (
        <div className="max-w-6xl w-full">
            <div className="flex justify-center mb-4">
                <Logomark />
            </div>
            <h1 className="text-4xl font-bold text-center mb-2">{heading}</h1>
            <p className="text-center text-muted mb-8">{subheading}</p>

            {/* Use cases grid - 2 rows x 3 columns */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {useCases.map((useCase: UseCaseDefinition) => (
                    <LemonCard
                        key={useCase.key}
                        className="p-4 cursor-pointer"
                        onClick={() => selectUseCase(useCase.key)}
                        hoverEffect
                        data-attr={`use-case-${useCase.key}`}
                    >
                        <div className="flex flex-col items-center text-center gap-3">
                            <div className="text-3xl">
                                {getProductIcon(useCase.iconKey, {
                                    iconColor: useCase.iconColor,
                                    className: 'text-3xl',
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
                    className="p-4 cursor-pointer"
                    onClick={() => selectPickMyself()}
                    hoverEffect
                    data-attr="pick-myself-card"
                >
                    <div className="flex flex-col items-center text-center gap-3">
                        <div className="text-3xl">
                            <IconCursor className="text-3xl" color="rgb(100, 116, 139)" />
                        </div>
                        <div>
                            <div className="font-semibold mb-1">I'll pick myself</div>
                            <p className="text-muted text-sm mb-0">I know exactly which products I need</p>
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
            className="relative cursor-pointer hover:transform-none p-4"
            onClick={onToggle}
            focused={selected}
            hoverEffect
        >
            <div className="flex flex-col items-center text-center gap-2">
                <div className="text-3xl">
                    {getProductIcon(product.icon, {
                        iconColor: product.iconColor,
                        className: 'text-3xl',
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
    const { toggleProduct, setFirstProductOnboarding, handleStartOnboarding, setShowAllProducts, setStep } =
        useActions(productSelectionLogic)

    const availableRecommendedProducts = recommendedProducts.filter(isAvailableOnboardingProductKey)
    const availableOtherProducts = otherProducts.filter(isAvailableOnboardingProductKey)

    return (
        <div className="max-w-6xl w-full">
            <div className="flex justify-center mb-4">
                <Logomark />
            </div>
            <h1 className="text-4xl font-bold text-center mb-2">Which products would you like to use?</h1>
            <p className="text-center text-muted mb-8">
                {recommendationSourceLabel ? (
                    <>We've pre-selected some products {recommendationSourceLabel}. Feel free to change or add more.</>
                ) : (
                    <>Select all that apply — you can pick more than one!</>
                )}
            </p>

            {/* Browsing history banner */}
            {recommendationSource === 'browsing_history' && <BrowsingHistoryBanner />}

            {/* Products list */}
            <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,190px))] gap-3 justify-center w-full">
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
                    <div className="flex gap-2 items-center justify-center">
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
                <button
                    className="text-muted hover:text-default text-sm cursor-pointer"
                    onClick={() => setStep('choose_path')}
                >
                    ← Go back
                </button>
            </div>
        </div>
    )
}

export function LegacyProductSelection(): JSX.Element {
    const { currentStep } = useValues(productSelectionLogic)

    return (
        <div className="flex flex-col flex-1 w-full min-h-full p-4 items-center justify-center bg-primary overflow-x-hidden">
            <div className="flex flex-col items-center justify-center flex-grow w-full">
                {currentStep === 'choose_path' && <ChoosePathStep />}
                {currentStep === 'product_selection' && <ProductSelectionStep />}
                {currentStep === 'choose_path' && <OnboardingExitAction />}
            </div>
        </div>
    )
}
