import { IconInfo } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lowercaseFirstLetter } from 'lib/utils'
import posthog from 'posthog-js'
import { useEffect } from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getProductIcon } from 'scenes/products/Products'

import { AvailableFeature } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { PayGateMiniButton } from './PayGateMiniButton'
import { payGateMiniLogic } from './payGateMiniLogic'

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
    const { productWithFeature, featureInfo, featureAvailableOnOrg, gateVariant } = useValues(
        payGateMiniLogic({ featureKey: feature, currentUsage })
    )
    const { preflight } = useValues(preflightLogic)
    const { billing, billingLoading } = useValues(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { hideUpgradeModal } = useActions(upgradeModalLogic)

    useEffect(() => {
        if (gateVariant) {
            posthog.capture('pay gate shown', {
                product_key: productWithFeature?.type,
                feature: feature,
                gate_variant: gateVariant,
            })
        }
    }, [gateVariant])

    if (billingLoading) {
        return null
    }

    if (gateVariant && preflight?.instance_preferences?.disable_paid_fs) {
        return null // Don't show anything if paid features are explicitly disabled
    }

    return featureFlags[FEATURE_FLAGS.SUBSCRIBE_FROM_PAYGATE] === 'test' ? (
        gateVariant && productWithFeature && featureInfo && !overrideShouldShowGate ? (
            <div
                className={clsx(
                    className,
                    background && 'bg-side border border-border',
                    'PayGateMini rounded flex flex-col items-center p-4 text-center'
                )}
            >
                <div className="flex text-4xl text-warning">
                    {getProductIcon(productWithFeature.name, featureInfo.icon_key)}
                </div>
                <h3>{featureInfo.name}</h3>
                {featureAvailableOnOrg?.limit && gateVariant !== 'move-to-cloud' ? (
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
                                {featureAvailableOnOrg.limit} {featureAvailableOnOrg.unit}
                            </span>
                        </p>
                        <p>
                            Please upgrade your <b>{productWithFeature.name}</b> plan to create more {featureInfo.name}
                        </p>
                    </div>
                ) : (
                    <>
                        <p>{featureInfo.description}</p>
                        <p>
                            {gateVariant === 'move-to-cloud' ? (
                                <>This feature is only available on PostHog Cloud.</>
                            ) : (
                                <>
                                    Upgrade your <b>{productWithFeature?.name}</b> plan to use this feature.
                                </>
                            )}
                        </p>
                    </>
                )}
                {isGrandfathered && (
                    <div className="flex gap-x-2 bg-side p-4 rounded text-left mb-4">
                        <IconInfo className="text-muted text-2xl" />
                        <p className="text-muted mb-0">
                            Your plan does not include this feature, but previously set settings may remain. Please
                            upgrade your plan to regain access.
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
                <PayGateMiniButton product={productWithFeature} featureInfo={featureInfo} gateVariant={gateVariant} />
            </div>
        ) : (
            <div className={className}>{children}</div>
        )
    ) : gateVariant && productWithFeature && featureInfo && !overrideShouldShowGate ? (
        <div
            className={clsx(
                className,
                background && 'bg-side border border-border',
                'PayGateMini rounded flex flex-col items-center p-4 text-center'
            )}
        >
            <div className="flex text-4xl text-warning">
                {getProductIcon(productWithFeature.name, featureInfo.icon_key)}
            </div>
            <h3>{featureInfo.name}</h3>
            {featureAvailableOnOrg?.limit && gateVariant !== 'move-to-cloud' ? (
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
                            {featureAvailableOnOrg.limit} {featureAvailableOnOrg.unit}
                        </span>
                    </p>
                    <p>
                        Please upgrade your <b>{productWithFeature.name}</b> plan to create more {featureInfo.name}
                    </p>
                </div>
            ) : (
                <p>
                    {gateVariant === 'move-to-cloud' ? (
                        <>On PostHog Cloud, you can </>
                    ) : (
                        <>
                            Upgrade your <b>{productWithFeature?.name}</b> plan to{' '}
                        </>
                    )}
                    {featureInfo.description ? lowercaseFirstLetter(featureInfo.description) : 'use this feature.'}
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
            <LemonButton
                to={
                    gateVariant === 'add-card'
                        ? `/organization/billing?products=${productWithFeature.type}`
                        : gateVariant === 'contact-sales'
                        ? `mailto:sales@posthog.com?subject=Inquiring about ${featureInfo.name}`
                        : gateVariant === 'move-to-cloud'
                        ? 'https://us.posthog.com/signup?utm_medium=in-product&utm_campaign=move-to-cloud'
                        : undefined
                }
                type="primary"
                center
                onClick={() => {
                    hideUpgradeModal()
                    posthog.capture('pay gate CTA clicked', {
                        product_key: productWithFeature?.type,
                        feature: feature,
                        gate_variant: gateVariant,
                    })
                }}
            >
                {gateVariant === 'add-card'
                    ? billing?.has_active_subscription
                        ? `Upgrade ${productWithFeature?.name}`
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
