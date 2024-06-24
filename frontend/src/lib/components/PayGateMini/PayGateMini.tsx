import { IconInfo, IconOpenSidebar } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import { useEffect } from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getProductIcon } from 'scenes/products/Products'

import {
    AvailableFeature,
    BillingProductV2AddonType,
    BillingProductV2Type,
    BillingV2FeatureType,
    BillingV2Type,
} from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { PayGateButton } from './PayGateButton'
import { payGateMiniLogic } from './payGateMiniLogic'

export interface PayGateMiniProps {
    feature: AvailableFeature
    currentUsage?: number
    /**
     * The content to show when the feature is available. Will show nothing if children is undefined.
     */
    children?: React.ReactNode
    overrideShouldShowGate?: boolean
    className?: string
    background?: boolean
    isGrandfathered?: boolean
    docsLink?: string
}

/** A sort of paywall for premium features.
 *
 * Simply shows its children when the feature is available,
 * otherwise it presents upsell UI with the call to action that's most relevant for the circumstances.
 */
export function PayGateMini({
    feature,
    currentUsage,
    className,
    children,
    overrideShouldShowGate,
    background = true,
    isGrandfathered,
    docsLink,
}: PayGateMiniProps): JSX.Element | null {
    const {
        productWithFeature,
        featureInfo,
        featureAvailableOnOrg,
        gateVariant,
        isAddonProduct,
        featureInfoOnNextPlan,
    } = useValues(payGateMiniLogic({ featureKey: feature, currentUsage }))
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { billing, billingLoading } = useValues(billingLogic)
    const { hideUpgradeModal } = useActions(upgradeModalLogic)

    const scrollToProduct = !(featureInfo?.key === AvailableFeature.ORGANIZATIONS_PROJECTS && !isAddonProduct)

    useEffect(() => {
        if (gateVariant) {
            posthog.capture('pay gate shown', {
                product_key: productWithFeature?.type,
                feature: feature,
                gate_variant: gateVariant,
            })
        }
    }, [gateVariant])

    const handleCtaClick = (): void => {
        hideUpgradeModal()
        posthog.capture('pay gate CTA clicked', {
            product_key: productWithFeature?.type,
            feature: feature,
            gate_variant: gateVariant,
        })
    }

    if (billingLoading) {
        return null
    }

    if (gateVariant && preflight?.instance_preferences?.disable_paid_fs) {
        return null // Don't show anything if paid features are explicitly disabled
    }

    if (gateVariant && productWithFeature && featureInfo && !overrideShouldShowGate) {
        return (
            <PayGateContent
                className={className}
                background={background}
                featureInfo={featureInfo}
                featureAvailableOnOrg={featureAvailableOnOrg}
                gateVariant={gateVariant}
                productWithFeature={productWithFeature}
                isGrandfathered={isGrandfathered}
                isAddonProduct={isAddonProduct}
                billing={billing}
                featureInfoOnNextPlan={featureInfoOnNextPlan}
                handleCtaClick={handleCtaClick}
            >
                <div className="flex items-center justify-center space-x-3">
                    <PayGateButton
                        gateVariant={gateVariant}
                        productWithFeature={productWithFeature}
                        featureInfo={featureInfo}
                        onCtaClick={handleCtaClick}
                        billing={billing}
                        scrollToProduct={scrollToProduct}
                        isAddonProduct={isAddonProduct}
                    />
                    {docsLink && isCloudOrDev && (
                        <LemonButton
                            type="secondary"
                            to={`${docsLink}?utm_medium=in-product&utm_campaign=${feature}-upgrade-learn-more`}
                            targetBlank
                            center
                            data-attr={`${feature}-learn-more`}
                        >
                            Learn more <IconOpenSidebar className="ml-2" />
                        </LemonButton>
                    )}
                </div>
            </PayGateContent>
        )
    }

    return <div className={className}>{children}</div>
}

interface PayGateContentProps {
    className?: string
    background: boolean
    featureInfo: BillingV2FeatureType
    featureAvailableOnOrg?: BillingV2FeatureType | null
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type
    isGrandfathered?: boolean
    isAddonProduct?: boolean
    billing: BillingV2Type | null
    featureInfoOnNextPlan?: BillingV2FeatureType
    children: React.ReactNode
    handleCtaClick: () => void
}

function PayGateContent({
    className,
    background,
    featureInfo,
    featureAvailableOnOrg,
    gateVariant,
    productWithFeature,
    isGrandfathered,
    isAddonProduct,
    billing,
    featureInfoOnNextPlan,
    children,
    handleCtaClick,
}: PayGateContentProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <div
            className={clsx(
                className,
                background && 'bg-bg-3000 border border-border',
                'PayGateMini rounded flex flex-col items-center p-4 text-center'
            )}
        >
            <div className="flex text-4xl text-warning mb-2">
                {getProductIcon(productWithFeature.name, featureInfo.icon_key)}
            </div>
            <h2>{featureInfo.name}</h2>
            {renderUsageLimitMessage(
                featureAvailableOnOrg,
                featureInfoOnNextPlan,
                gateVariant,
                featureInfo,
                productWithFeature,
                billing,
                featureFlags,
                isAddonProduct,
                handleCtaClick
            )}
            {isGrandfathered && <GrandfatheredMessage />}
            {featureInfo.docsUrl && <DocsLink url={featureInfo.docsUrl} />}
            {children}
        </div>
    )
}

const renderUsageLimitMessage = (
    featureAvailableOnOrg: BillingV2FeatureType | null | undefined,
    featureInfoOnNextPlan: BillingV2FeatureType | undefined,
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null,
    featureInfo: BillingV2FeatureType,
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type,
    billing: BillingV2Type | null,
    featureFlags: FeatureFlagsSet,
    isAddonProduct?: boolean,
    handleCtaClick?: () => void
): JSX.Element => {
    if (featureAvailableOnOrg?.limit && gateVariant !== 'move-to-cloud') {
        return (
            <div>
                <p>
                    You've reached your usage limit for{' '}
                    <Tooltip title={featureInfo.description}>
                        <span>
                            <b>{featureInfo.name}</b>
                            <IconInfo className="ml-0.5 text-muted" />
                        </span>
                    </Tooltip>
                    .
                </p>
                <p className="border border-border bg-bg-3000 rounded p-4">
                    <b>Your current plan limit:</b>{' '}
                    <span>
                        {featureAvailableOnOrg.limit} {featureAvailableOnOrg.unit}
                    </span>
                </p>
                {featureInfo.key === AvailableFeature.ORGANIZATIONS_PROJECTS && !isAddonProduct ? (
                    <>
                        <p>
                            Please enter your credit card details by subscribing to any product (eg. Product analytics
                            or Session replay) to create up to <b>{featureInfoOnNextPlan?.limit} projects</b>.
                        </p>
                        <p className="italic text-xs text-muted mb-4">
                            Need unlimited projects? Check out the{' '}
                            <Link to="/organization/billing?products=platform_and_support" onClick={handleCtaClick}>
                                Teams addon
                            </Link>
                            .
                        </p>
                    </>
                ) : featureFlags[FEATURE_FLAGS.SUBSCRIBE_TO_ALL_PRODUCTS] === 'test' &&
                  billing?.subscription_level === 'free' &&
                  !isAddonProduct ? (
                    <p>Upgrade to create more {featureInfo.name}</p>
                ) : (
                    <p>
                        Upgrade your <b>{productWithFeature.name}</b> plan to create more {featureInfo.name}
                    </p>
                )}
            </div>
        )
    }
    return (
        <>
            <p className="max-w-140">{featureInfo.description}</p>
            <p>{renderGateVariantMessage(gateVariant, productWithFeature, billing, featureFlags, isAddonProduct)}</p>
        </>
    )
}

const renderGateVariantMessage = (
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null,
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type,
    billing: BillingV2Type | null,
    featureFlags: FeatureFlagsSet,
    isAddonProduct?: boolean
): JSX.Element => {
    if (gateVariant === 'move-to-cloud') {
        return <>This feature is only available on PostHog Cloud.</>
    } else if (isAddonProduct) {
        return (
            <>
                Subscribe to the <b>{productWithFeature?.name}</b> addon to use this feature.
            </>
        )
    } else if (
        featureFlags[FEATURE_FLAGS.SUBSCRIBE_TO_ALL_PRODUCTS] === 'test' &&
        billing?.subscription_level === 'free'
    ) {
        return <>Upgrade to use this feature.</>
    }

    return (
        <>
            Upgrade your <b>{productWithFeature?.name}</b> plan to use this feature.
        </>
    )
}

const GrandfatheredMessage = (): JSX.Element => {
    return (
        <div className="flex gap-x-2 bg-bg-3000 p-4 rounded text-left mb-4">
            <IconInfo className="text-muted text-2xl" />
            <p className="text-muted mb-0">
                Your plan does not include this feature, but previously set settings may remain. Please upgrade your
                plan to regain access.
            </p>
        </div>
    )
}

const DocsLink = ({ url }: { url: string }): JSX.Element => {
    return (
        <div className="mb-4">
            <Link to={url} target="_blank">
                Learn more in PostHog Docs.
            </Link>
        </div>
    )
}
