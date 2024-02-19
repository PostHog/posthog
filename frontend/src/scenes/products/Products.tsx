import * as Icons from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
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

function OnboardingCompletedButton({
    productUrl,
    onboardingUrl,
    getStartedActionOverride,
}: {
    productUrl: string
    onboardingUrl: string
    productKey: ProductKey
    getStartedActionOverride?: () => void
}): JSX.Element {
    return (
        <>
            <LemonButton type="secondary" to={productUrl}>
                Go to product
            </LemonButton>
            <LemonButton
                type="tertiary"
                onClick={() => {
                    if (getStartedActionOverride) {
                        getStartedActionOverride()
                    }
                    router.actions.push(onboardingUrl)
                }}
            >
                Set up again
            </LemonButton>
        </>
    )
}

function OnboardingNotCompletedButton({
    url,
    getStartedActionOverride,
}: {
    url: string
    productKey: ProductKey
    getStartedActionOverride?: () => void
}): JSX.Element {
    return (
        <LemonButton
            type="primary"
            onClick={() => {
                if (getStartedActionOverride) {
                    getStartedActionOverride()
                }
                router.actions.push(url)
            }}
        >
            Get started
        </LemonButton>
    )
}

export function getProductIcon(iconKey?: string | null, className?: string): JSX.Element {
    return Icons[iconKey || 'IconLogomark'].render({ className })
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
            className={clsx('flex gap-4', vertical ? 'flex-col max-w-80' : 'items-center', className)}
            key={product.type}
        >
            <div className="flex">
                <div>
                    <div className="bg-mid rounded p-2">{getProductIcon(product.icon_key, 'text-2xl')}</div>
                </div>
            </div>
            <div className="flex-1">
                <h3 className={`bold ${vertical ? 'mb-2' : 'mb-0'}`}>{product.name}</h3>
                <p className="grow m-0">{product.description}</p>
            </div>
            <div className={`flex gap-x-2 flex-0 items-center ${!vertical && 'justify-end'}`}>
                {onboardingCompleted ? (
                    <OnboardingCompletedButton
                        productUrl={getProductUri(product.type as ProductKey, featureFlags)}
                        onboardingUrl={urls.onboarding(product.type)}
                        productKey={product.type as ProductKey}
                        getStartedActionOverride={() => {
                            setIncludeIntro(false)
                        }}
                    />
                ) : (
                    <div>
                        <OnboardingNotCompletedButton
                            url={urls.onboarding(product.type)}
                            productKey={product.type as ProductKey}
                            getStartedActionOverride={() => {
                                setIncludeIntro(false)
                                const includeFirstOnboardingProductOnUserProperties = user?.date_joined
                                    ? new Date(user?.date_joined) > new Date('2024-01-10T00:00:00Z')
                                    : false
                                reportOnboardingProductSelected(
                                    product.type,
                                    includeFirstOnboardingProductOnUserProperties
                                )
                                getStartedActionOverride && getStartedActionOverride()
                            }}
                        />
                    </div>
                )}
            </div>
        </LemonCard>
    )
}

export function Products(): JSX.Element {
    const { billing } = useValues(billingLogic)
    const { isFirstProductOnboarding } = useValues(onboardingLogic)
    const products = billing?.products || []

    return (
        <div className="flex flex-col flex-1 w-full h-full p-6 items-center justify-center bg-mid">
            <div className="mb-8">
                <h1 className="text-center text-4xl">
                    Pick your {isFirstProductOnboarding ? 'first' : 'next'} product.
                </h1>
                <p className="text-center">
                    Pick your {isFirstProductOnboarding ? 'first' : 'next'} product to get started with. You can set up
                    any others you'd like later.
                </p>
            </div>
            {products.length > 0 ? (
                <>
                    <div className="flex w-full max-w-300 justify-center gap-6 flex-wrap">
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
