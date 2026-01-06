import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import * as Icons from '@posthog/icons'
import { IconArrowRight, IconChevronDown, IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonLabel, LemonSelect, LemonTextArea, Link } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand/Logomark'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { UseCaseDefinition } from '../productRecommendations'
import { availableOnboardingProducts } from '../utils'
import { productSelectionLogic } from './productSelectionLogic'

const isValidIconKey = (key: string): key is keyof typeof Icons => key in Icons
type AvailableOnboardingProductKey = keyof typeof availableOnboardingProducts

const isAvailableOnboardingProductKey = (key: string | ProductKey): key is AvailableOnboardingProductKey =>
    key in availableOnboardingProducts

export function getProductIcon(
    iconKey?: string | null,
    { iconColor, className }: { iconColor?: string; className?: string } = {}
): JSX.Element {
    if (iconKey && isValidIconKey(iconKey)) {
        const IconComponent = Icons[iconKey]
        return <IconComponent className={className} color={iconColor} />
    }

    return <Icons.IconLogomark className={className} />
}

function BrowsingHistoryBanner(): JSX.Element | null {
    const { hasBrowsingHistory, browsingHistoryLabels } = useValues(productSelectionLogic)

    if (!hasBrowsingHistory) {
        return null
    }

    return (
        <LemonBanner type="info" className="mb-6">
            Based on your browsing history ({browsingHistoryLabels.slice(0, 3).join(', ')}), we've tailored
            recommendations to your interests.
        </LemonBanner>
    )
}

function ChoosePathStep(): JSX.Element {
    const {
        useCases,
        aiDescription,
        aiRecommendationLoading,
        aiRecommendationError,
        hasBrowsingHistory,
        browsingHistoryLabels,
    } = useValues(productSelectionLogic)
    const { selectUseCase, setAiDescription, submitAiRecommendation, selectPickMyself } =
        useActions(productSelectionLogic)

    const aiRecommendationsEnabled = useFeatureFlag('ONBOARDING_AI_PRODUCT_RECOMMENDATIONS', 'test')

    return (
        <div className="max-w-4xl w-full">
            <div className="flex justify-center mb-4">
                <Logomark />
            </div>
            <h1 className="text-4xl font-bold text-center mb-2">What do you want to do with PostHog?</h1>
            <p className="text-center text-muted mb-8">
                {aiRecommendationsEnabled
                    ? "Describe your goals and we'll recommend the right products for you"
                    : 'Pick a goal to get started with the right products'}
            </p>

            {/* AI Input - Full width and prominent (behind feature flag) */}
            {aiRecommendationsEnabled && (
                <>
                    <div className="mb-8">
                        <LemonTextArea
                            placeholder="e.g., I want to understand why users drop off during checkout and run experiments to improve conversion..."
                            value={aiDescription}
                            onChange={(value) => setAiDescription(value)}
                            rows={3}
                        />
                        <div className="flex items-center justify-between mt-3">
                            <p className="text-muted text-xs mb-0">
                                {hasBrowsingHistory && (
                                    <>
                                        We'll also consider your interest in{' '}
                                        <em>{browsingHistoryLabels.slice(0, 2).join(' and ')}</em> based on your docs
                                        browsing history.
                                    </>
                                )}
                            </p>
                            <LemonButton
                                type="primary"
                                onClick={() => submitAiRecommendation()}
                                loading={aiRecommendationLoading}
                                disabledReason={
                                    !aiDescription.trim() ? 'Please describe what you want to achieve' : undefined
                                }
                                icon={<IconSparkles />}
                                data-attr="ai-recommend-products"
                            >
                                Get recommendations
                            </LemonButton>
                        </div>
                    </div>

                    {/* Error banner */}
                    {aiRecommendationError && (
                        <LemonBanner type="error" className="mb-4">
                            Failed to get recommendations. Please try again or pick a goal below.
                        </LemonBanner>
                    )}

                    {/* Divider */}
                    <div className="flex items-center gap-4 mb-8">
                        <div className="flex-1 border-t border-border" />
                        <span className="text-muted text-sm">or pick a common goal</span>
                        <div className="flex-1 border-t border-border" />
                    </div>
                </>
            )}

            {/* Use cases grid - 2 rows x 3 columns */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {useCases.map((useCase: UseCaseDefinition) => (
                    <LemonCard
                        key={useCase.key}
                        className={clsx(
                            'p-4',
                            aiRecommendationLoading ? 'opacity-50 pointer-events-none' : 'cursor-pointer'
                        )}
                        onClick={() => !aiRecommendationLoading && selectUseCase(useCase.key)}
                        hoverEffect={!aiRecommendationLoading}
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
                    className={clsx(
                        'p-4',
                        aiRecommendationLoading ? 'opacity-50 pointer-events-none' : 'cursor-pointer'
                    )}
                    onClick={() => !aiRecommendationLoading && selectPickMyself()}
                    hoverEffect={!aiRecommendationLoading}
                    data-attr="pick-myself-card"
                >
                    <div className="flex flex-col items-center text-center gap-3">
                        <div className="text-3xl">
                            <Icons.IconCursor className="text-3xl" color="rgb(100, 116, 139)" />
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
    const { currentTeam } = useValues(teamLogic)
    const onboardingCompleted = currentTeam?.has_completed_onboarding_for?.[productKey]

    return (
        <LemonCard
            data-attr={`${productKey}-onboarding-card`}
            className="cursor-pointer hover:transform-none p-4 w-full md:w-[calc(33.333%-0.5rem)]"
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
                    <h3 className="font-semibold mb-1 text-sm">
                        {product.name}
                        {onboardingCompleted && <span className="ml-1 text-xs text-muted font-normal">(set up)</span>}
                    </h3>
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
        aiRecommendation,
        recommendationSource,
    } = useValues(productSelectionLogic)
    const { toggleProduct, setFirstProductOnboarding, handleStartOnboarding, setShowAllProducts, setStep } =
        useActions(productSelectionLogic)
    const { showInviteModal } = useActions(inviteLogic)

    const availableRecommendedProducts = recommendedProducts.filter(isAvailableOnboardingProductKey)
    const availableOtherProducts = otherProducts.filter(isAvailableOnboardingProductKey)

    return (
        <div className="max-w-[800px] w-full">
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

            {/* AI reasoning banner */}
            {recommendationSource === 'ai' && aiRecommendation?.reasoning && (
                <LemonBanner type="ai" className="mb-6">
                    {aiRecommendation.reasoning}
                </LemonBanner>
            )}

            {/* Browsing history banner */}
            {recommendationSource === 'browsing_history' && <BrowsingHistoryBanner />}

            {/* Products list - single unified grid */}
            <div className="flex flex-wrap justify-center gap-3">
                {/* Recommended products first */}
                {availableRecommendedProducts.map((productKey) => (
                    <ProductCard
                        key={productKey}
                        productKey={productKey}
                        selected={selectedProducts.includes(productKey)}
                        onToggle={() => toggleProduct(productKey)}
                    />
                ))}

                {/* Other products - shown/hidden based on toggle */}
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

            {/* Show more toggle - only show when collapsed */}
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

            {/* Continue button */}
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

            <p className="text-center mt-8 text-muted">
                Need help from a team member? <Link onClick={() => showInviteModal()}>Invite them</Link>
            </p>
        </div>
    )
}

export function ProductSelection(): JSX.Element {
    const { currentStep } = useValues(productSelectionLogic)

    return (
        <div className="flex flex-col flex-1 w-full min-h-full p-4 items-center justify-center bg-primary overflow-x-hidden">
            <div className="flex flex-col items-center justify-center flex-grow w-full">
                {currentStep === 'choose_path' && <ChoosePathStep />}
                {currentStep === 'product_selection' && <ProductSelectionStep />}
            </div>
        </div>
    )
}

export default ProductSelection
