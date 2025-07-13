import './PlanCards.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { HeartHog } from 'lib/components/hedgehogs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'

import { type BillingProductV2Type } from '~/types'

import { onboardingLogic } from '../onboardingLogic'
import { FreeTierLimits } from './FreeTierLimits'

type Feature = {
    name: string
    available: boolean
}

enum Plan {
    TOTALLY_FREE = 'totally_free',
    RIDICULOUSLY_CHEAP = 'ridiculously_cheap',
}

type PlanData = {
    title: string
    plan: Plan
    billingPlanKeyPrefix: 'free' | 'paid'
    subtitle: string
    pricePreface?: string
    price: string
    priceSuffix?: string
    priceSubtitle?: string | JSX.Element
    features: Feature[]
    ctaText?: string
    ctaAction?: 'billing' | 'next'
}

type PlanCardProps = {
    planData: PlanData
    product: BillingProductV2Type
    highlight?: boolean
    hogPosition?: 'top-right' | 'top-left'
}

export const PlanCard: React.FC<PlanCardProps> = ({ planData, product, highlight, hogPosition = 'top-right' }) => {
    const { billing } = useValues(billingLogic)
    const { billingProductLoading } = useValues(billingProductLogic({ product }))
    const [isHovering, setIsHovering] = useState<boolean | undefined>(undefined)
    const { goToNextStep } = useActions(onboardingLogic)
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)

    const productPlan = product.plans.find((plan) => plan.plan_key?.startsWith(planData.billingPlanKeyPrefix))
    const platformPlan = billing?.products
        ?.find((p) => p.type === 'platform_and_support')
        ?.plans.find((p) => p.plan_key?.startsWith(planData.billingPlanKeyPrefix))

    const dataRetentionFeature = productPlan?.features.find(
        (feature) => feature.key === `${product.type}_data_retention`
    )
    const projectLimitFeature = platformPlan?.features.find((feature) => feature.key === 'organizations_projects')

    const features = [
        ...(projectLimitFeature?.limit
            ? [
                  {
                      name: `${projectLimitFeature.limit} project${projectLimitFeature.limit === 1 ? '' : 's'}`,
                      available: true,
                  },
              ]
            : []),
        ...(dataRetentionFeature?.limit
            ? [{ name: `${dataRetentionFeature.limit}-year data retention`, available: true }]
            : []),
        ...planData.features,
    ]

    const hogPositionClass = hogPosition === 'top-right' ? 'CheekyHogTopRight' : 'CheekyHogTopLeft'

    return (
        <div className="relative" onMouseEnter={() => setIsHovering(true)} onMouseLeave={() => setIsHovering(false)}>
            <HeartHog
                width="100"
                height="100"
                className={clsx(
                    hogPositionClass,
                    isHovering === true && `${hogPositionClass}--peek`,
                    isHovering === false && `${hogPositionClass}--hide`
                )}
            />
            <div
                className={clsx(
                    'relative flex flex-col h-full p-6 bg-bg-light dark:bg-bg-depth rounded-xs border transition-transform transform hover:scale-[1.02] hover:shadow-lg',
                    highlight ? 'border-2 border-accent-active' : 'border-gray-200 dark:border-gray-700'
                )}
            >
                {planData.plan === Plan.RIDICULOUSLY_CHEAP && (
                    <div className="absolute top-0 right-0 -mt-4 -mr-4 px-3 py-1 bg-bg-light dark:bg-bg-depth rounded-xs text-xs text-accent-active font-semibold shadow-md border-accent-active border-2">
                        Free tier included!
                    </div>
                )}
                <header className="mb-0">
                    <h3 className="text-2xl font-bold mb-0 text-gray-800 dark:text-gray-100">{planData.title}</h3>
                    <p className="text-muted dark:text-gray-400">{planData.subtitle}</p>
                </header>
                <section className="mb-3">
                    <div className="flex items-baseline gap-1">
                        {planData.pricePreface && (
                            <span className="text-base text-muted-alt dark:text-gray-300">{planData.pricePreface}</span>
                        )}
                        <span className="text-xl font-extrabold text-gray-900 dark:text-white">{planData.price}</span>
                        {planData.priceSuffix && (
                            <span className="text-base text-muted-alt dark:text-gray-300">{planData.priceSuffix}</span>
                        )}
                    </div>
                    {planData.priceSubtitle && (
                        <p className="text-xs text-gray-500 dark:text-gray-400">{planData.priceSubtitle}</p>
                    )}
                </section>
                <section className="flex-1 mb-3">
                    <ul className="deprecated-space-y-2">
                        {features.map((feature) => (
                            <li key={feature.name} className="flex items-center">
                                {feature.available ? (
                                    <IconCheck className="w-4 h-4 text-success mr-2" />
                                ) : (
                                    <IconX className="w-4 h-4 text-gray-400 mr-2" />
                                )}
                                <span className="text-sm font-medium text-gray-800 dark:text-gray-200">
                                    {feature.name}
                                </span>
                            </li>
                        ))}
                    </ul>
                </section>
                <footer className="mt-auto">
                    {planData.ctaAction === 'billing' && (
                        <BillingUpgradeCTA
                            type="primary"
                            status={highlight ? 'alt' : undefined}
                            center
                            disabledReason={billingProductLoading && 'Please wait...'}
                            disableClientSideRouting
                            loading={!!billingProductLoading}
                            onClick={() =>
                                startPaymentEntryFlow(product, window.location.pathname + window.location.search)
                            }
                            data-attr="onboarding-subscribe-button"
                            fullWidth
                        >
                            {planData.ctaText}
                        </BillingUpgradeCTA>
                    )}
                    {planData.ctaAction === 'next' && (
                        <LemonButton
                            type="primary"
                            fullWidth
                            center
                            status={highlight ? 'alt' : undefined}
                            onClick={() => goToNextStep()}
                        >
                            {planData.ctaText}
                        </LemonButton>
                    )}
                </footer>
            </div>
        </div>
    )
}

const PLANS_DATA: PlanData[] = [
    {
        title: 'Free',
        plan: Plan.TOTALLY_FREE,
        billingPlanKeyPrefix: 'free',
        subtitle: 'No credit card required',
        price: 'Free',
        features: [
            { name: 'Community support', available: true },
            { name: 'Capped usage', available: false },
            { name: 'Group analytics + Data pipeline addons', available: false },
            { name: 'Happy hedgehogs', available: false },
        ],
        ctaText: 'Select this plan',
        ctaAction: 'next',
    },
    {
        title: 'Pay-as-you-go',
        plan: Plan.RIDICULOUSLY_CHEAP,
        billingPlanKeyPrefix: 'paid',
        subtitle: 'Usage-based pricing after free tier',
        pricePreface: 'Starts at',
        price: '$0',
        priceSuffix: '/mo',
        features: [
            { name: 'Email support', available: true },
            { name: 'Unlimited usage', available: true },
            { name: 'Group analytics + Data pipeline addons', available: true },
            { name: 'Happy hedgehogs', available: true },
        ],
        ctaText: 'Unlock all features',
        ctaAction: 'billing',
    },
]

export const PlanCards: React.FC<{ product: BillingProductV2Type }> = ({ product }) => {
    return (
        <div className="px-4">
            <div className="py-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {PLANS_DATA.map((planData, index) => (
                        <PlanCard
                            key={planData.plan}
                            planData={planData}
                            product={product}
                            highlight={planData.plan === Plan.RIDICULOUSLY_CHEAP}
                            hogPosition={index === 0 ? 'top-left' : 'top-right'}
                        />
                    ))}
                </div>
                <FreeTierLimits />
            </div>
        </div>
    )
}

export default PlanCards
