import { IconChevronDown, IconDocument } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useRef } from 'react'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType, BillingProductV2Type, BillingV2TierType } from '~/types'

import { summarizeUsage } from './billing-utils'
import { BillingGauge } from './BillingGauge'
import { BillingLimit } from './BillingLimit'
import { billingLogic } from './billingLogic'
import { BillingProductAddon } from './BillingProductAddon'
import { billingProductLogic } from './billingProductLogic'
import { BillingProductPricingTable } from './BillingProductPricingTable'
import { ProductPricingModal } from './ProductPricingModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

export const getTierDescription = (
    tiers: BillingV2TierType[],
    i: number,
    product: BillingProductV2Type | BillingProductV2AddonType,
    interval: string
): string => {
    return i === 0
        ? `First ${summarizeUsage(tiers[i].up_to)} ${product.unit}s / ${interval}`
        : tiers[i].up_to
        ? `${summarizeUsage(tiers?.[i - 1].up_to || null)} - ${summarizeUsage(tiers[i].up_to)}`
        : `> ${summarizeUsage(tiers?.[i - 1].up_to || null)}`
}

export const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const productRef = useRef<HTMLDivElement | null>(null)
    const { billing, redirectPath, isUnlicensedDebug } = useValues(billingLogic)
    const {
        customLimitUsd,
        showTierBreakdown,
        billingGaugeItems,
        isPricingModalOpen,
        currentAndUpgradePlans,
        surveyID,
        billingProductLoading,
    } = useValues(billingProductLogic({ product }))
    const { setShowTierBreakdown, toggleIsPricingModalOpen, setBillingProductLoading } = useActions(
        billingProductLogic({ product, productRef })
    )
    const { featureFlags } = useValues(featureFlagLogic)

    const { upgradePlan, currentPlan } = currentAndUpgradePlans

    const upgradeToPlanKey = upgradePlan?.plan_key
    const currentPlanKey = currentPlan?.plan_key

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        700: 'medium',
    })

    return (
        <div
            className={clsx('flex flex-wrap max-w-300 pb-8', {
                'flex-col pb-4': size === 'small',
            })}
            ref={ref}
        >
            <div className="border border-border rounded w-full bg-bg-light" ref={productRef}>
                <div className="border-b border-border rounded-t bg-bg-3000 p-4">
                    <div className="flex gap-4 items-center justify-between">
                        {getProductIcon(product.name, product.icon_key, 'text-2xl')}
                        <div>
                            <h3 className="font-bold mb-0">{product.name}</h3>
                            <div>{product.description}</div>
                        </div>
                        <div className="flex grow justify-end gap-x-2 items-center">
                            {product.docs_url && (
                                <LemonButton
                                    icon={<IconDocument />}
                                    size="small"
                                    to={product.docs_url}
                                    className="justify-end"
                                    tooltip="Read the docs"
                                />
                            )}
                            {product.contact_support ? (
                                <>
                                    {product.subscribed && <p className="m-0">Need to manage your plan?</p>}
                                    <LemonButton
                                        type="primary"
                                        to="mailto:sales@posthog.com?subject=Enterprise%20plan%20request"
                                    >
                                        Get in touch
                                    </LemonButton>
                                </>
                            ) : (
                                product.subscribed && (
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton
                                                    fullWidth
                                                    to="https://posthog.com/docs/billing/estimating-usage-costs#how-to-reduce-your-posthog-costs"
                                                >
                                                    Learn how to reduce your bill
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                )
                            )}
                            {surveyID && <UnsubscribeSurveyModal product={product} />}
                        </div>
                    </div>
                </div>
                <div className="px-8">
                    {product.percentage_usage > 1 && (
                        <LemonBanner className="mt-6" type="error">
                            You have exceeded the {customLimitUsd ? 'billing limit' : 'free tier limit'} for this
                            product.
                        </LemonBanner>
                    )}
                    <div className="flex w-full items-center gap-x-8">
                        {product.contact_support && (!product.subscribed || isUnlicensedDebug) ? (
                            <div className="py-8">
                                {!billing?.has_active_subscription && (
                                    <p className="ml-0">
                                        Every product subsciption comes with free platform features such as{' '}
                                        <b>Multiple projects, Integrations, Apps, and more</b>. Subscribe to one of the
                                        products above to get instant access.
                                    </p>
                                )}
                                <p className="m-0">
                                    Need additional platform and support (aka enterprise) features like <b>SAML SSO</b>,{' '}
                                    <b>advanced permissioning</b>, and more?{' '}
                                    <Link to="mailto:sales@posthog.com?subject=Enterprise%20plan%20request">
                                        Get in touch
                                    </Link>{' '}
                                    for a quick chat.
                                </p>
                            </div>
                        ) : (
                            !isUnlicensedDebug && (
                                <>
                                    {product.tiered ? (
                                        <>
                                            {product.subscribed && (
                                                <LemonButton
                                                    icon={
                                                        showTierBreakdown ? <IconChevronDown /> : <IconChevronRight />
                                                    }
                                                    onClick={() => setShowTierBreakdown(!showTierBreakdown)}
                                                />
                                            )}
                                            <div className="grow">
                                                <BillingGauge items={billingGaugeItems} product={product} />
                                            </div>
                                            {product.subscribed ? (
                                                <div className="flex justify-end gap-8 flex-wrap items-end">
                                                    <Tooltip
                                                        title={`The current ${
                                                            billing?.discount_percent ? 'discounted ' : ''
                                                        }amount you have been billed for this ${
                                                            billing?.billing_period?.interval
                                                        } so far. This number updates once daily.`}
                                                    >
                                                        <div className="flex flex-col items-center">
                                                            <div className="font-bold text-3xl leading-7">
                                                                $
                                                                {(
                                                                    parseFloat(product.current_amount_usd || '') *
                                                                    (1 -
                                                                        (billing?.discount_percent
                                                                            ? billing.discount_percent / 100
                                                                            : 0))
                                                                ).toFixed(2) || '0.00'}
                                                            </div>
                                                            <span className="text-xs text-muted">
                                                                {capitalizeFirstLetter(
                                                                    billing?.billing_period?.interval || ''
                                                                )}
                                                                -to-date
                                                            </span>
                                                        </div>
                                                    </Tooltip>
                                                    {product.tiers && (
                                                        <Tooltip
                                                            title={`This is roughly calculated based on your current bill${
                                                                billing?.discount_percent
                                                                    ? ', discounts on your account,'
                                                                    : ''
                                                            } and the remaining time left in this billing period. This number updates once daily.`}
                                                        >
                                                            <div className="flex flex-col items-center justify-end">
                                                                <div className="font-bold text-muted text-lg leading-5">
                                                                    $
                                                                    {(
                                                                        parseFloat(product.projected_amount_usd || '') *
                                                                        (1 -
                                                                            (billing?.discount_percent
                                                                                ? billing.discount_percent / 100
                                                                                : 0))
                                                                    ).toFixed(2) || '0.00'}
                                                                </div>
                                                                <span className="text-xs text-muted">Projected</span>
                                                            </div>
                                                        </Tooltip>
                                                    )}
                                                </div>
                                            ) : null}
                                        </>
                                    ) : product.current_amount_usd ? (
                                        <div className="my-8">
                                            <Tooltip
                                                title={`The current amount you will be billed for this ${billing?.billing_period?.interval}.`}
                                            >
                                                <div className="flex flex-col items-center">
                                                    <div className="font-bold text-3xl leading-7">
                                                        ${product.current_amount_usd}
                                                    </div>
                                                    <span className="text-xs text-muted">
                                                        per {billing?.billing_period?.interval || 'period'}
                                                    </span>
                                                </div>
                                            </Tooltip>
                                        </div>
                                    ) : null}
                                </>
                            )
                        )}
                    </div>
                    {product.price_description ? (
                        <LemonBanner type="info">
                            <span dangerouslySetInnerHTML={{ __html: product.price_description }} />
                        </LemonBanner>
                    ) : null}
                    {/* Table with tiers */}
                    {showTierBreakdown && <BillingProductPricingTable product={product} />}
                    {product.addons?.length > 0 && (
                        <div className="pb-8">
                            <h4 className="my-4">Add-ons</h4>
                            {billing?.subscription_level == 'free' && (
                                <LemonBanner type="warning" className="text-sm mb-4" hideIcon>
                                    <div className="flex justify-between items-center">
                                        <div>
                                            Add-ons are only available on paid plans. Upgrade to access these features.
                                        </div>
                                        <LemonButton
                                            className="shrink-0"
                                            to={`/api/billing/activate?products=all_products:&redirect_path=${redirectPath}&intent_product=${product.type}`}
                                            type="primary"
                                            status="alt"
                                            disableClientSideRouting
                                            loading={!!billingProductLoading}
                                            onClick={() => setBillingProductLoading(product.type)}
                                        >
                                            Upgrade now
                                        </LemonButton>
                                    </div>
                                </LemonBanner>
                            )}
                            <div className="gap-y-4 flex flex-col">
                                {product.addons
                                    // TODO: enhanced_persons: remove this filter
                                    .filter((addon) => {
                                        if (addon.inclusion_only) {
                                            if (featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]) {
                                                return false
                                            }
                                        }
                                        return true
                                    })
                                    .map((addon, i) => {
                                        return <BillingProductAddon key={i} addon={addon} />
                                    })}
                            </div>
                        </div>
                    )}
                </div>
                <BillingLimit product={product} />
            </div>
            <ProductPricingModal
                modalOpen={isPricingModalOpen}
                onClose={toggleIsPricingModalOpen}
                product={product}
                planKey={product.subscribed ? currentPlanKey : upgradeToPlanKey}
            />
        </div>
    )
}
