import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconInfo, IconOpenSidebar, IconUnlock } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { getProductIcon } from 'scenes/products/Products'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, BillingFeatureType, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { PayGateButton } from './PayGateButton'
import { PayGateMiniLogicProps, payGateMiniLogic } from './payGateMiniLogic'

export type PayGateMiniProps = PayGateMiniLogicProps & {
    /**
     * The content to show when the feature is available. Will show nothing if children is undefined.
     */
    children?: React.ReactNode
    overrideShouldShowGate?: boolean
    className?: string
    background?: boolean
    isGrandfathered?: boolean
    docsLink?: string
    /**
     * Custom loading state to show while billing data is loading
     */
    loadingSkeleton?: JSX.Element
    /**
     * Actions
     */
    handleSubmit?: () => void
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
    loadingSkeleton,
    handleSubmit,
}: PayGateMiniProps): JSX.Element | null {
    const { productWithFeature, featureInfo, gateVariant, bypassPaywall, ctaLabel } = useValues(
        payGateMiniLogic({ feature, currentUsage })
    )
    const { setBypassPaywall } = useActions(payGateMiniLogic({ feature, currentUsage }))
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { billingLoading } = useValues(billingLogic)
    const { user } = useValues(userLogic)

    useEffect(() => {
        if (gateVariant) {
            posthog.capture('pay gate shown', {
                product_key: productWithFeature?.type,
                feature: feature,
                gate_variant: gateVariant,
                cta_label: ctaLabel,
            })
        }
    }, [gateVariant, ctaLabel]) // oxlint-disable-line react-hooks/exhaustive-deps

    const handleCtaClick = (): void => {
        if (handleSubmit) {
            handleSubmit()
        }
        posthog.capture('pay gate CTA clicked', {
            product_key: productWithFeature?.type,
            feature: feature,
            gate_variant: gateVariant,
            cta_label: ctaLabel,
        })
    }

    if (billingLoading) {
        return (
            loadingSkeleton || (
                <div
                    className={clsx(
                        className,
                        background && 'bg-primary border border-primary',
                        'PayGateMini rounded flex flex-col items-center p-4 text-center'
                    )}
                >
                    <LemonSkeleton className="w-20 h-10 mb-2" />
                    <LemonSkeleton className="w-48 h-12 mb-2" />
                    <LemonSkeleton className="w-1/2 h-6 mb-2" />
                    <LemonSkeleton className="w-1/2 h-6 mb-2" />
                    <div className="flex items-center justify-center gap-x-2 mt-3">
                        <LemonSkeleton className="w-32 h-10" />
                        <LemonSkeleton className="w-32 h-10" />
                    </div>
                </div>
            )
        )
    }

    if (gateVariant && preflight?.instance_preferences?.disable_paid_fs) {
        return null // Don't show anything if paid features are explicitly disabled
    }

    if (gateVariant && productWithFeature && featureInfo && !overrideShouldShowGate && !bypassPaywall) {
        return (
            <PayGateContent
                feature={feature}
                currentUsage={currentUsage}
                className={className}
                background={background}
                isGrandfathered={isGrandfathered}
                handleCtaClick={handleCtaClick}
            >
                <div className="flex items-center justify-center deprecated-space-x-3">
                    <PayGateButton feature={feature} currentUsage={currentUsage} onClick={handleCtaClick} />
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

                    {user?.is_impersonated && (
                        <LemonButton
                            type="secondary"
                            icon={<IconUnlock />}
                            tooltip="Bypass this paywall - (UI only)"
                            onClick={() => setBypassPaywall(true)}
                        >
                            Bypass paywall
                        </LemonButton>
                    )}
                </div>
            </PayGateContent>
        )
    }

    return <div className={className}>{children}</div>
}

interface PayGateContentProps extends PayGateMiniLogicProps {
    className?: string
    background: boolean
    isGrandfathered?: boolean
    children: React.ReactNode
    handleCtaClick: () => void
}

function PayGateContent({
    feature,
    currentUsage,
    className,
    background,
    isGrandfathered,
    children,
    handleCtaClick,
}: PayGateContentProps): JSX.Element | null {
    const {
        productWithFeature,
        featureInfo,
        featureAvailableOnOrg,
        gateVariant,
        isAddonProduct,
        featureInfoOnNextPlan,
    } = useValues(payGateMiniLogic({ feature, currentUsage }))

    if (!productWithFeature || !featureInfo) {
        return null
    }

    return (
        <div
            className={clsx(
                className,
                background && 'bg-primary border border-primary',
                'PayGateMini rounded flex flex-col items-center p-4 text-center'
            )}
        >
            <div className="flex mb-2 text-4xl text-warning">
                {getProductIcon(productWithFeature.name, featureInfo.icon_key)}
            </div>
            <h2>{featureInfo.name}</h2>
            {renderUsageLimitMessage(
                featureAvailableOnOrg,
                featureInfoOnNextPlan,
                gateVariant,
                featureInfo,
                productWithFeature,
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
    featureAvailableOnOrg: BillingFeatureType | null | undefined,
    featureInfoOnNextPlan: BillingFeatureType | undefined,
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null,
    featureInfo: BillingFeatureType,
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type,
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
                            <IconInfo className="ml-0.5 text-secondary" />
                        </span>
                    </Tooltip>
                    .
                </p>
                <p className="p-4 border rounded border-primary bg-primary">
                    <b>Your current plan limit:</b>{' '}
                    <span>
                        {featureAvailableOnOrg.limit} {featureAvailableOnOrg.unit}
                    </span>
                </p>
                {featureInfo.key === AvailableFeature.ORGANIZATIONS_PROJECTS && !isAddonProduct ? (
                    <>
                        {featureInfoOnNextPlan?.limit && (
                            <p>
                                Please enter your credit card details to create up to{' '}
                                <b>{featureInfoOnNextPlan?.limit} projects</b>.
                            </p>
                        )}
                        <p className="mb-4 text-xs italic text-secondary">
                            Need unlimited projects? Check out one of our{' '}
                            <Link to="/organization/billing?products=platform_and_support" onClick={handleCtaClick}>
                                platform add-ons
                            </Link>
                            .
                        </p>
                    </>
                ) : !isAddonProduct ? (
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
            <p>{renderGateVariantMessage(gateVariant, productWithFeature, isAddonProduct)}</p>
        </>
    )
}

const renderGateVariantMessage = (
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null,
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type,
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
    }

    return <>Upgrade to use this feature.</>
}

const GrandfatheredMessage = (): JSX.Element => {
    return (
        <div className="flex mb-4 text-left rounded gap-x-2 bg-primary">
            <IconInfo className="text-2xl text-secondary" />
            <p className="mb-0 text-secondary">
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
