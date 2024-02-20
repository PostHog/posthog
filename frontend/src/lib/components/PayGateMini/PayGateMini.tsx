import './PayGateMini.scss'

import { Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { IconPremium } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lowercaseFirstLetter } from 'lib/utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getProductIcon } from 'scenes/products/Products'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

export interface PayGateMiniProps {
    feature: AvailableFeature
    children: React.ReactNode
    overrideShouldShowGate?: boolean
    className?: string
}

/** A sort of paywall for premium features.
 *
 * Simply shows its children when the feature is available,
 * otherwise it presents upsell UI with the call to action that's most relevant for the circumstances.
 */
export function PayGateMini({
    feature,
    className,
    children,
    overrideShouldShowGate,
}: PayGateMiniProps): JSX.Element | null {
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { billing } = useValues(billingLogic)

    const product = billing?.products.find((product) => product.features.some((f) => f.key === feature))
    const featureInfo = product?.features.find((f) => f.key === feature)
    const minimumPlan = product?.plans.find((plan) => plan.features.some((f) => f.key === feature))

    let gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null = null
    if (!overrideShouldShowGate && !hasAvailableFeature(feature)) {
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
        <div className={clsx('PayGateMini', className)}>
            <div className="PayGateMini__icon">{getProductIcon(featureInfo.icon_key) || <IconPremium />}</div>
            <h3>{featureInfo.name}</h3>
            <p className="mb-0">
                {gateVariant === 'move-to-cloud' ? (
                    <>On PostHog Cloud, you can </>
                ) : (
                    <>Upgrade your {product?.name} plan to </>
                )}
                {featureInfo.description ? lowercaseFirstLetter(featureInfo.description) : 'use this feature.'}
            </p>
            <div className="PayGateMini__cta">
                {featureInfo.docsUrl && (
                    <>
                        {' '}
                        <Link to={featureInfo.docsUrl} target="_blank">
                            Learn more in PostHog Docs.
                        </Link>
                    </>
                )}
            </div>
            <LemonButton
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
            >
                {gateVariant === 'add-card'
                    ? billing?.has_active_subscription
                        ? `Upgrade ${product?.name}`
                        : 'Subscribe now'
                    : gateVariant === 'contact-sales'
                    ? 'Contact sales'
                    : 'Move to PostHog Cloud'}
            </LemonButton>
        </div>
    ) : (
        <div className={className}>{children}</div>
    )
}
