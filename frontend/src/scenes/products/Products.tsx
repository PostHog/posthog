import * as Icons from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSelect, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { availableOnboardingProducts, getProductUri, onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { OnboardingProduct, ProductKey } from '~/types'

import { productsLogic } from './productsLogic'

export const scene: SceneExport = {
    component: Products,
}

export function getProductIcon(color: string, iconKey?: string | null, className?: string): JSX.Element {
    const Icon = Icons[iconKey || 'IconLogomark']
    return <Icon className={className} color={color} />
}

export function SelectableProductCard({
    product,
    productKey,
    onClick,
    orientation = 'vertical',
    className,
    selected = false,
}: {
    product: OnboardingProduct
    productKey: string
    onClick: () => void
    orientation?: 'horizontal' | 'vertical'
    className?: string
    selected?: boolean
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const onboardingCompleted = currentTeam?.has_completed_onboarding_for?.[productKey]
    const vertical = orientation === 'vertical'
    return (
        <LemonCard
            data-attr={`${productKey}-onboarding-card`}
            className={clsx('flex justify-center cursor-pointer', vertical ? 'flex-col' : 'items-center', className)}
            key={productKey}
            onClick={onClick}
            focused={selected}
        >
            {onboardingCompleted && (
                <Tooltip
                    title="You've already set up this product. Click to return to this product's page."
                    placement="right"
                >
                    <div
                        className="relative"
                        onClick={(e) => {
                            e.stopPropagation()
                            router.actions.push(getProductUri(productKey as ProductKey))
                        }}
                        data-attr={`return-to-${productKey}`}
                    >
                        <Icons.IconCheckCircle className="absolute top-0 right-0" color="green" />
                    </div>
                </Tooltip>
            )}
            <div className="grid grid-rows-[repeat(2,_48px)] justify-items-center">
                <div className="self-center">{getProductIcon(product.iconColor, product.icon, 'text-2xl')}</div>
                <div className="font-bold text-center self-start text-md">{product.name}</div>
            </div>
        </LemonCard>
    )
}

export function ProductCard({
    product,
    productKey,
    getStartedActionOverride,
    orientation = 'vertical',
    className,
}: {
    product: OnboardingProduct
    productKey: string
    getStartedActionOverride?: () => void
    orientation?: 'horizontal' | 'vertical'
    className?: string
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { setIncludeIntro } = useActions(onboardingLogic)
    const { addProductIntent } = useActions(teamLogic)
    const onboardingCompleted = currentTeam?.has_completed_onboarding_for?.[productKey]
    const vertical = orientation === 'vertical'

    return (
        <LemonCard
            data-attr={`${productKey}-onboarding-card`}
            className={clsx('flex justify-center cursor-pointer', vertical ? 'flex-col' : 'items-center', className)}
            key={productKey}
            onClick={() => {
                setIncludeIntro(false)
                if (!onboardingCompleted) {
                    getStartedActionOverride && getStartedActionOverride()
                }
                router.actions.push(urls.onboarding(productKey))
                addProductIntent({
                    product_type: productKey as ProductKey,
                    intent_context: 'onboarding product selected',
                })
            }}
        >
            {onboardingCompleted && (
                <Tooltip
                    title="You've already set up this product. Click to return to this product's page."
                    placement="right"
                >
                    <div
                        className="relative"
                        onClick={(e) => {
                            e.stopPropagation()
                            router.actions.push(getProductUri(productKey as ProductKey))
                        }}
                        data-attr={`return-to-${productKey}`}
                    >
                        <Icons.IconCheckCircle className="absolute top-0 right-0" color="green" />
                    </div>
                </Tooltip>
            )}
            <div className="grid grid-rows-[repeat(2,_48px)] justify-items-center">
                <div className="self-center">{getProductIcon(product.iconColor, product.icon, 'text-2xl')}</div>
                <div className="font-bold text-center self-start text-md">{product.name}</div>
            </div>
        </LemonCard>
    )
}

export function Products(): JSX.Element {
    const { isFirstProductOnboarding } = useValues(onboardingLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { addProductIntent } = useActions(teamLogic)
    const { setIncludeIntro } = useActions(onboardingLogic)

    const { toggleSelectedProduct, setFirstProductOnboarding } = useActions(productsLogic)
    const { selectedProducts, firstProductOnboarding } = useValues(productsLogic)

    return (
        <div className="flex flex-col flex-1 w-full px-6 items-center justify-center bg-bg-3000 h-[calc(100vh-var(--breadcrumbs-height-full)-2*var(--scene-padding))]">
            {true ? (
                <>
                    <div className="mb-8">
                        <h2 className="text-center text-4xl">Which products would you like to use?</h2>
                    </div>
                    <div className="grid gap-4 grid-rows-[160px] grid-cols-[repeat(2,_minmax(min-content,_160px))] md:grid-cols-[repeat(3,_minmax(min-content,_160px))] ">
                        {Object.keys(availableOnboardingProducts).map((productKey) => (
                            <SelectableProductCard
                                product={availableOnboardingProducts[productKey]}
                                key={productKey}
                                productKey={productKey}
                                onClick={() => {
                                    toggleSelectedProduct(productKey)
                                }}
                                selected={selectedProducts.includes(productKey)}
                            />
                        ))}
                    </div>
                    <div className="mt-8 flex gap-2 justify-center items-center">
                        {selectedProducts.length > 1 ? (
                            <>
                                <LemonLabel>Get started with</LemonLabel>
                                <LemonSelect
                                    value={firstProductOnboarding}
                                    options={selectedProducts.map((productKey) => ({
                                        label: availableOnboardingProducts[productKey].name,
                                        value: productKey,
                                    }))}
                                    onChange={(value) => value && setFirstProductOnboarding(value)}
                                    placeholder="Select a product"
                                />
                                <LemonButton type="primary">Go</LemonButton>
                            </>
                        ) : (
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    const firstProductKey = selectedProducts[0]
                                    setIncludeIntro(false)
                                    router.actions.push(urls.onboarding(firstProductKey))
                                    addProductIntent({
                                        product_type: firstProductKey as ProductKey,
                                        intent_context: 'onboarding product selected',
                                    })
                                }}
                                disabledReason={
                                    selectedProducts.length === 0 ? 'Select a product to start with' : undefined
                                }
                            >
                                Get started
                            </LemonButton>
                        )}
                    </div>
                    <p className="text-center mt-8">
                        Need help from a team member? <Link onClick={() => showInviteModal()}>Invite them</Link>
                    </p>
                </>
            ) : (
                <>
                    <div className="mb-8">
                        {isFirstProductOnboarding ? (
                            <h2 className="text-center text-4xl">Where do you want to start?</h2>
                        ) : (
                            <h2 className="text-center text-4xl">Welcome back. What would you like to set up?</h2>
                        )}
                        {isFirstProductOnboarding && (
                            <p className="text-center">You can set up additional products later.</p>
                        )}
                    </div>
                    <div className="grid gap-4 grid-rows-[160px] grid-cols-[repeat(2,_minmax(min-content,_160px))] md:grid-cols-[repeat(3,_minmax(min-content,_160px))] ">
                        {Object.keys(availableOnboardingProducts).map((productKey) => (
                            <ProductCard
                                product={availableOnboardingProducts[productKey]}
                                key={productKey}
                                productKey={productKey}
                            />
                        ))}
                    </div>
                    <p className="text-center mt-8">
                        Need help from a team member? <Link onClick={() => showInviteModal()}>Invite them</Link>
                    </p>
                </>
            )}
        </div>
    )
}
