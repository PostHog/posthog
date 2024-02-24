import * as Icons from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconCheckCircleOutline } from 'lib/lemon-ui/icons'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { getProductUri, onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { BillingProductV2Type, ProductKey } from '~/types'

export const scene: SceneExport = {
    component: Products,
}

const ProductNameToColor = {
    'Product analytics': 'blue',
    'Session replay': 'var(--warning)',
    'Feature flags & A/B testing': 'seagreen',
    Surveys: 'salmon',
}

export function getProductIcon(productName: string, iconKey?: string | null, className?: string): JSX.Element {
    const Icon = Icons[iconKey || 'IconLogomark']
    return <Icon className={className} color={ProductNameToColor[productName] || 'none'} />
}

export function ProductCard({
    product,
    getStartedActionOverride,
    orientation = 'vertical',
    className,
}: {
    product: BillingProductV2Type
    getStartedActionOverride?: () => void
    orientation?: 'horizontal' | 'vertical'
    className?: string
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { setIncludeIntro } = useActions(onboardingLogic)
    const { user } = useValues(userLogic)
    const { reportOnboardingProductSelected } = useActions(eventUsageLogic)
    const onboardingCompleted = currentTeam?.has_completed_onboarding_for?.[product.type]
    const vertical = orientation === 'vertical'

    return (
        <LemonCard
            data-attr={`${product.type}-onboarding-card`}
            className={clsx('flex justify-center cursor-pointer', vertical ? 'flex-col' : 'items-center', className)}
            key={product.type}
            onClick={() => {
                setIncludeIntro(false)
                if (!onboardingCompleted) {
                    const includeFirstOnboardingProductOnUserProperties = user?.date_joined
                        ? new Date(user?.date_joined) > new Date('2024-01-10T00:00:00Z')
                        : false
                    reportOnboardingProductSelected(product.type, includeFirstOnboardingProductOnUserProperties)
                    getStartedActionOverride && getStartedActionOverride()
                }
                router.actions.push(urls.onboarding(product.type))
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
                            router.actions.push(getProductUri(product.type as ProductKey, featureFlags))
                        }}
                    >
                        <IconCheckCircleOutline className="absolute top-0 right-0" color="green" />
                    </div>
                </Tooltip>
            )}
            <div className="grid grid-rows-[repeat(2,_48px)] justify-items-center">
                <div className="self-center">{getProductIcon(product.name, product.icon_key, 'text-2xl')}</div>
                <div className="font-bold text-center self-start text-md">{product.name}</div>
            </div>
        </LemonCard>
    )
}

export function Products(): JSX.Element {
    const { billing } = useValues(billingLogic)
    const { isFirstProductOnboarding } = useValues(onboardingLogic)
    const products = billing?.products || []

    return (
        <div className="flex flex-col flex-1 w-full px-6 items-center justify-center bg-mid h-[calc(100vh-var(--breadcrumbs-height-full)-2*var(--scene-padding))]">
            <div className="mb-8">
                {isFirstProductOnboarding ? (
                    <h2 className="text-center text-4xl">Where do you want to start?</h2>
                ) : (
                    <h2 className="text-center text-4xl">Welcome back. What would you like to set up?</h2>
                )}
                {isFirstProductOnboarding && <p className="text-center">You can set up additional products later.</p>}
            </div>
            {products.length > 0 ? (
                <>
                    <div className="grid gap-4 grid-rows-[150px] grid-cols-[repeat(2,_minmax(min-content,_150px))] md:grid-cols-[repeat(4,_minmax(min-content,_150px))] ">
                        {products
                            .filter(
                                (product) =>
                                    !product.contact_support &&
                                    !product.inclusion_only &&
                                    product.type !== 'data_warehouse'
                            )
                            .map((product) => (
                                <ProductCard product={product} key={product.type} />
                            ))}
                    </div>
                </>
            ) : (
                <Spinner className="text-3xl" />
            )}
        </div>
    )
}
