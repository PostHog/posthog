import * as Icons from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { availableOnboardingProducts, getProductUri, onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { OnboardingProduct, ProductKey } from '~/types'

export const scene: SceneExport = {
    component: Products,
}

export function getProductIcon(color: string, iconKey?: string | null, className?: string): JSX.Element {
    const Icon = Icons[iconKey || 'IconLogomark']
    return <Icon className={className} color={color} />
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
    const { user } = useValues(userLogic)
    const { reportOnboardingProductSelected } = useActions(eventUsageLogic)
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
                    const includeFirstOnboardingProductOnUserProperties = user?.date_joined
                        ? new Date(user?.date_joined) > new Date('2024-01-10T00:00:00Z')
                        : false
                    reportOnboardingProductSelected(productKey, includeFirstOnboardingProductOnUserProperties)
                    getStartedActionOverride && getStartedActionOverride()
                }
                router.actions.push(urls.onboarding(productKey))
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

    return (
        <div className="flex flex-col flex-1 w-full px-6 items-center justify-center bg-bg-3000 h-[calc(100vh-var(--breadcrumbs-height-full)-2*var(--scene-padding))]">
            <div className="mb-8">
                {isFirstProductOnboarding ? (
                    <h2 className="text-center text-4xl">Where do you want to start?</h2>
                ) : (
                    <h2 className="text-center text-4xl">Welcome back. What would you like to set up?</h2>
                )}
                {isFirstProductOnboarding && <p className="text-center">You can set up additional products later.</p>}
            </div>
            <>
                <div className="grid gap-4 grid-rows-[160px] grid-cols-[repeat(2,_minmax(min-content,_160px))] md:grid-cols-[repeat(5,_minmax(min-content,_160px))] ">
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
        </div>
    )
}
