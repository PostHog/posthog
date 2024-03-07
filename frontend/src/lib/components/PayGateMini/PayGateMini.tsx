import { IconInfo } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lowercaseFirstLetter } from 'lib/utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getProductIcon } from 'scenes/products/Products'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { BillingUpgradeCTA } from '../BillingUpgradeCTA'

export interface PayGateMiniProps {
    feature: AvailableFeature
    currentUsage?: number
    children: React.ReactNode
    overrideShouldShowGate?: boolean
    className?: string
    background?: boolean
    isGrandfathered?: boolean
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
}: PayGateMiniProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { hasAvailableFeature, availableFeature } = useValues(userLogic)
    const { billing } = useValues(billingLogic)
    const { hideUpgradeModal } = useActions(sceneLogic)

    const product = billing?.products.find((product) => product.features?.some((f) => f.key === feature))
    const featureInfo = product?.features.find((f) => f.key === feature)
    const featureDetailsWithLimit = availableFeature(feature)
    const minimumPlan = product?.plans.find((plan) => plan.features?.some((f) => f.key === feature))

    let gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null = null
    if (!overrideShouldShowGate && !hasAvailableFeature(feature, currentUsage)) {
        if (isCloudOrDev) {
            if (!minimumPlan || minimumPlan.contact_support) {
                gateVariant = 'contact-sales'
            } else {
                gateVariant = 'add-card'
            }
        } else {
            gateVariant = 'move-to-cloud'
        }
    }

    if (gateVariant && preflight?.instance_preferences?.disable_paid_fs) {
        return null // Don't show anything if paid features are explicitly disabled
    }

    return gateVariant && product && featureInfo ? (
        <div
            className={clsx(
                className,
                background && 'bg-side border border-border',
                'PayGateMini rounded flex flex-col items-center p-4 text-center'
            )}
            data-attr="paygate"
        >
            <div className="flex text-4xl text-warning">{getProductIcon(product.name, featureInfo.icon_key)}</div>
            <h3>{featureInfo.name}</h3>
            {featureDetailsWithLimit?.limit && gateVariant !== 'move-to-cloud' ? (
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
                    <p className="border border-border bg-side rounded p-4">
                        <b>Your current plan limit:</b>{' '}
                        <span>
                            {featureDetailsWithLimit.limit} {featureDetailsWithLimit.unit}
                        </span>
                    </p>
                    <p>
                        Please upgrade your <b>{product.name}</b> plan to create more {featureInfo.name}
                    </p>
                </div>
            ) : (
                <p>
                    {gateVariant === 'move-to-cloud' ? (
                        <>On PostHog Cloud, you can </>
                    ) : (
                        <>
                            Upgrade your <b>{product.name}</b> plan to{' '}
                            {featureInfo.description
                                ? lowercaseFirstLetter(featureInfo.description)
                                : 'use this feature.'}
                        </>
                    )}
                </p>
            )}
            {isGrandfathered && (
                <div className="flex gap-x-2 bg-side p-4 rounded text-left mb-4">
                    <IconInfo className="text-muted text-2xl" />
                    <p className="text-muted mb-0">
                        Your plan does not include this feature, but previously set settings may remain. Please upgrade
                        your plan to regain access.
                    </p>
                </div>
            )}
            {featureInfo.docsUrl && (
                <div className="mb-4">
                    <>
                        <Link to={featureInfo.docsUrl} target="_blank">
                            Learn more in PostHog Docs.
                        </Link>
                    </>
                </div>
            )}
            <BillingUpgradeCTA
                data-attr="paygate-mini-cta"
                to={
                    gateVariant === 'add-card'
                        ? `/organization/billing?products=${product.type}`
                        : gateVariant === 'contact-sales'
                        ? `mailto:sales@posthog.com?subject=Inquiring about ${featureInfo.name}`
                        : gateVariant === 'move-to-cloud'
                        ? 'https://us.posthog.com/signup?utm_medium=in-product&utm_campaign=move-to-cloud'
                        : undefined
                }
                type="primary"
                center
                onClick={hideUpgradeModal}
            >
                {gateVariant === 'add-card'
                    ? featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'subscribe'
                        ? `Subscribe to ${product.name}`
                        : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                          !billing?.has_active_subscription
                        ? 'Add credit card'
                        : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                          billing?.has_active_subscription
                        ? `Add paid plan for ${product.name}`
                        : `Upgrade ${product.name}`
                    : gateVariant === 'contact-sales'
                    ? 'Contact sales'
                    : 'Move to PostHog Cloud'}
            </BillingUpgradeCTA>
        </div>
    ) : (
        <div className={className}>{children}</div>
    )
}
