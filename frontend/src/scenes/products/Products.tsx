import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import * as Icons from '@posthog/icons'
import { IconArrowRight, IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSelect, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { availableOnboardingProducts } from 'scenes/onboarding/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingProduct } from '~/types'

import { productsLogic } from './productsLogic'

export const scene: SceneExport = {
    component: Products,
}

const isValidIconKey = (key: string): key is keyof typeof Icons => key in Icons
type AvailableOnboardingProductKey = keyof typeof availableOnboardingProducts
const AVAILABLE_ONBOARDING_PRODUCT_KEYS = Object.keys(availableOnboardingProducts) as AvailableOnboardingProductKey[]
const isAvailableOnboardingProductKey = (key: string | ProductKey): key is AvailableOnboardingProductKey =>
    key in availableOnboardingProducts

export function getProductIcon(color: string, iconKey?: string | null, className?: string): JSX.Element {
    const resolvedKey: keyof typeof Icons = iconKey && isValidIconKey(iconKey) ? iconKey : 'IconLogomark'
    const Icon = Icons[resolvedKey] as (props: { className?: string; color?: string }) => JSX.Element
    return <Icon className={className} color={color} />
}

export function SelectableProductCard({
    product,
    productKey,
    onClick,
    orientation = 'vertical',
    showDescription = false,
    className,
    selected = false,
}: {
    product: OnboardingProduct
    productKey: string
    onClick: () => void
    orientation?: 'horizontal' | 'vertical'
    showDescription?: boolean
    className?: string
    selected?: boolean
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const onboardingCompleted = currentTeam?.has_completed_onboarding_for?.[productKey]
    const vertical = orientation === 'vertical'
    const description = product.description || ''

    const shouldShowTooltip = (!showDescription && product.description) || onboardingCompleted

    const tooltipContent = (
        <>
            {!showDescription && product.description && (
                <>
                    {product.description}
                    <br />
                </>
            )}
            {onboardingCompleted && <em>You've already set up this app. Click to return to its page.</em>}
        </>
    )

    const card = (
        <LemonCard
            data-attr={`${productKey}-onboarding-card`}
            className={clsx(
                'flex cursor-pointer',
                vertical ? 'flex-col justify-center' : 'items-center hover:transform-none',
                className
            )}
            key={productKey}
            onClick={onClick}
            focused={selected}
            hoverEffect={!vertical}
        >
            {vertical ? (
                // Vertical layout
                <div className="flex flex-col gap-2 p-4 select-none">
                    <div className="flex justify-center">
                        {getProductIcon(product.iconColor, product.icon, 'text-2xl')}
                    </div>
                    <div className="font-bold text-center text-md">{product.name}</div>
                </div>
            ) : (
                // Horizontal layout with description
                <div className="flex items-start gap-4">
                    <div className="text-3xl flex-shrink-0">
                        {getProductIcon(product.iconColor, product.icon, 'text-3xl')}
                    </div>
                    <div className="flex-1">
                        <h3 className="font-semibold mb-1">{product.name}</h3>
                        {showDescription && description && <p className="text-muted text-sm mb-0">{description}</p>}
                    </div>
                </div>
            )}
        </LemonCard>
    )

    return shouldShowTooltip ? <Tooltip title={tooltipContent}>{card}</Tooltip> : card
}

export function Products(): JSX.Element {
    const { showInviteModal } = useActions(inviteLogic)
    const { toggleSelectedProduct, setFirstProductOnboarding, handleStartOnboarding } = useActions(productsLogic)
    const { selectedProducts, firstProductOnboarding, preSelectedProducts, useCase, isUseCaseOnboardingEnabled } =
        useValues(productsLogic)
    const { skipOnboarding } = useActions(onboardingLogic)
    const { hasIngestedEvent } = useValues(teamLogic)
    const [showAllProducts, setShowAllProducts] = useState(false)

    // Get all non-recommended products
    const availablePreSelectedProducts = preSelectedProducts.filter(isAvailableOnboardingProductKey)
    const otherProducts = AVAILABLE_ONBOARDING_PRODUCT_KEYS.filter((key) => !availablePreSelectedProducts.includes(key))

    return (
        <div className="flex flex-col flex-1 w-full min-h-full p-4 items-center justify-center bg-primary overflow-x-hidden">
            <>
                {/* Back button at the top */}
                {isUseCaseOnboardingEnabled && (
                    <div className="w-full max-w-[800px] mb-4">
                        <button
                            className="text-muted hover:text-default text-sm flex items-center gap-1 cursor-pointer"
                            onClick={() => router.actions.push(urls.useCaseSelection())}
                        >
                            ← Go back to change my goal
                        </button>
                    </div>
                )}

                <div className="flex flex-col justify-center flex-grow items-center">
                    <div className="mb-8">
                        <h2 className="text-center text-4xl">Which apps would you like to use?</h2>
                        <p className="text-center text-muted">
                            {isUseCaseOnboardingEnabled
                                ? `We've pre-selected some products based on your goal. Feel free to change or add more.`
                                : "Don't worry – you can pick more than one! Please select all that apply."}
                        </p>
                    </div>

                    <div className="flex flex-col-reverse sm:flex-col gap-6 md:gap-12 justify-center items-center w-full">
                        {isUseCaseOnboardingEnabled ? (
                            // NEW LAYOUT: Horizontal cards with recommendations (when use case onboarding is enabled)
                            <div className="max-w-[800px] w-full flex flex-col">
                                {/* Recommended products - always shown if we have them */}
                                {availablePreSelectedProducts.length > 0 && (
                                    <div className="flex flex-col gap-3 mb-4">
                                        {availablePreSelectedProducts.map((productKey) => (
                                            <SelectableProductCard
                                                key={productKey}
                                                product={availableOnboardingProducts[productKey]}
                                                productKey={productKey}
                                                onClick={() => toggleSelectedProduct(productKey)}
                                                selected={selectedProducts.includes(productKey)}
                                                orientation="horizontal"
                                                showDescription={true}
                                                className="w-full"
                                            />
                                        ))}
                                    </div>
                                )}

                                {/* Other products section - always rendered to avoid layout shift */}
                                {availablePreSelectedProducts.length > 0 && otherProducts.length > 0 && (
                                    <div className="flex flex-col items-center">
                                        {/* Toggle button */}
                                        <button
                                            onClick={() => {
                                                const newState = !showAllProducts
                                                setShowAllProducts(newState)
                                                if (window.posthog && newState) {
                                                    window.posthog.capture('onboarding_show_all_products_clicked', {
                                                        use_case: useCase,
                                                        recommended_count: availablePreSelectedProducts.length,
                                                    })
                                                }
                                            }}
                                            className="text-muted hover:text-default text-sm mb-2 flex items-center gap-1 cursor-pointer"
                                        >
                                            {showAllProducts ? (
                                                <>
                                                    <IconChevronDown className="rotate-180 text-xs" /> Hide other apps
                                                </>
                                            ) : (
                                                <>
                                                    Show all apps ({otherProducts.length} more){' '}
                                                    <IconChevronDown className="text-xs" />
                                                </>
                                            )}
                                        </button>

                                        {/* Products with smooth height transition */}
                                        <div
                                            className="w-full overflow-hidden transition-all duration-300 ease-in-out"
                                            style={{
                                                maxHeight: showAllProducts ? '2000px' : '0px',
                                                opacity: showAllProducts ? 1 : 0,
                                            }}
                                        >
                                            <div className="flex flex-col gap-3 mb-6">
                                                {otherProducts.map((productKey) => (
                                                    <SelectableProductCard
                                                        key={productKey}
                                                        product={availableOnboardingProducts[productKey]}
                                                        productKey={productKey}
                                                        onClick={() => toggleSelectedProduct(productKey)}
                                                        selected={selectedProducts.includes(productKey)}
                                                        orientation="horizontal"
                                                        showDescription={true}
                                                        className="w-full"
                                                    />
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ) : (
                            // OLD LAYOUT: Flex wrap layout (when use case onboarding is disabled)
                            <div className="flex flex-row flex-wrap gap-4 justify-center max-w-[680px]">
                                {AVAILABLE_ONBOARDING_PRODUCT_KEYS.map((productKey) => (
                                    <SelectableProductCard
                                        key={productKey}
                                        product={availableOnboardingProducts[productKey]}
                                        productKey={productKey}
                                        onClick={() => toggleSelectedProduct(productKey)}
                                        selected={selectedProducts.includes(productKey)}
                                        orientation="vertical"
                                        showDescription={false}
                                        className="w-[160px]"
                                    />
                                ))}
                            </div>
                        )}

                        <div className="flex flex-col items-center gap-4 w-full">
                            <div
                                className={clsx(
                                    'flex flex-col-reverse sm:flex-row gap-4 items-center justify-center w-full',
                                    hasIngestedEvent && 'sm:justify-between sm:px-4'
                                )}
                            >
                                {hasIngestedEvent && (
                                    <LemonButton
                                        status="alt"
                                        onClick={() => {
                                            skipOnboarding()
                                        }}
                                    >
                                        Skip onboarding
                                    </LemonButton>
                                )}
                                {selectedProducts.length > 1 ? (
                                    <div className="flex gap-2 items-center justify-center">
                                        <LemonLabel>Start with</LemonLabel>
                                        <LemonSelect
                                            value={firstProductOnboarding}
                                            options={selectedProducts.map((productKey) => ({
                                                label: isAvailableOnboardingProductKey(productKey)
                                                    ? availableOnboardingProducts[productKey].name
                                                    : productKey,
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
                                        disabledReason={
                                            selectedProducts.length === 0 ? 'Select a product to start with' : undefined
                                        }
                                    >
                                        Get started
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
                <p className="text-center mt-8">
                    Need help from a team member? <Link onClick={() => showInviteModal()}>Invite them</Link>
                </p>
            </>
        </div>
    )
}
