import * as Icons from '@posthog/icons'
import { IconArrowRight, IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSelect, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { availableOnboardingProducts, getProductUri } from 'scenes/onboarding/onboardingLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'

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
                        <IconCheckCircle className="absolute top-0 right-0" color="green" />
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
    const { showInviteModal } = useActions(inviteLogic)

    const { toggleSelectedProduct, setFirstProductOnboarding, handleStartOnboarding } = useActions(productsLogic)
    const { selectedProducts, firstProductOnboarding } = useValues(productsLogic)

    return (
        <div className="flex flex-col flex-1 w-full px-6 items-center justify-center bg-bg-3000 h-[calc(100vh-var(--breadcrumbs-height-full)-2*var(--scene-padding))]">
            <>
                <div className="flex flex-col justify-center flex-grow items-center">
                    <div className="mb-8">
                        <h2 className="text-center text-4xl">Which products would you like to use?</h2>
                        <p className="text-center">
                            Don't worry &ndash; you can pick more than one! Please select all that apply.
                        </p>
                    </div>
                    <div className="grid gap-4 grid-rows-[160px] grid-cols-[repeat(2,_minmax(min-content,_160px))] md:grid-cols-[repeat(3,_minmax(min-content,_160px))] ">
                        {Object.keys(availableOnboardingProducts).map((productKey) => (
                            <SelectableProductCard
                                product={availableOnboardingProducts[productKey]}
                                key={productKey}
                                productKey={productKey}
                                onClick={() => {
                                    toggleSelectedProduct(productKey as ProductKey)
                                }}
                                selected={selectedProducts.includes(productKey as ProductKey)}
                                className={productKey === ProductKey.SURVEYS ? 'md:col-start-2' : ''}
                            />
                        ))}
                    </div>
                    <div className="mt-12 flex gap-2 justify-center items-center">
                        {selectedProducts.length > 1 ? (
                            <>
                                <LemonLabel>Start first with</LemonLabel>
                                <LemonSelect
                                    value={firstProductOnboarding}
                                    options={selectedProducts.map((productKey) => ({
                                        label: availableOnboardingProducts[productKey].name,
                                        value: productKey,
                                    }))}
                                    onChange={(value) => value && setFirstProductOnboarding(value)}
                                    placeholder="Select a product"
                                    className="bg-bg-light"
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
                            </>
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
                <p className="text-center mt-8">
                    Need help from a team member? <Link onClick={() => showInviteModal()}>Invite them</Link>
                </p>
            </>
        </div>
    )
}
