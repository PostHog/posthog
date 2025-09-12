import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronDown, IconDocument, IconInfo } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, humanFriendlyCurrency } from 'lib/utils'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType, BillingProductV2Type, BillingTierType, ProductKey } from '~/types'

import { BillingGauge } from './BillingGauge'
import { BillingLimit } from './BillingLimit'
import { BillingProductAddon } from './BillingProductAddon'
import { BillingProductPricingTable } from './BillingProductPricingTable'
import { ProductPricingModal } from './ProductPricingModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'
import { createGaugeItems, isProductVariantPrimary, summarizeUsage } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { REALTIME_DESTINATIONS_BILLING_START_DATE } from './constants'
import { paymentEntryLogic } from './paymentEntryLogic'

export const getTierDescription = (
    tiers: BillingTierType[],
    i: number,
    product: BillingProductV2Type | BillingProductV2AddonType,
    interval: string
): string => {
    return i === 0
        ? tiers[i].up_to
            ? `First ${summarizeUsage(tiers[i].up_to)} ${product.unit}s / ${interval}`
            : `All ${product.unit}s`
        : tiers[i].up_to
          ? `${summarizeUsage(tiers?.[i - 1].up_to || null)} - ${summarizeUsage(tiers[i].up_to)}`
          : `> ${summarizeUsage(tiers?.[i - 1].up_to || null)}`
}

export const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const productRef = useRef<HTMLDivElement | null>(null)
    const { billing, isUnlicensedDebug } = useValues(billingLogic)
    const {
        hasCustomLimitSet,
        showTierBreakdown,
        billingGaugeItems,
        isPricingModalOpen,
        currentAndUpgradePlans,
        surveyID,
        billingProductLoading,
        isProductWithVariants,
        visibleAddons,
        variantExpandedStates,
        projectedAmountExcludingAddons,
        productVariants,
        combinedMonetaryData,
        combinedMonetaryGaugeItems,
    } = useValues(billingProductLogic({ product }))
    const {
        setShowTierBreakdown,
        toggleIsPricingModalOpen,
        reportSurveyShown,
        setSurveyResponse,
        toggleVariantExpanded,
    } = useActions(billingProductLogic({ product, productRef }))
    const { featureFlags } = useValues(featureFlagLogic)

    const { upgradePlan, currentPlan } = currentAndUpgradePlans

    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)

    const productDisplayNameOverrides: Record<string, string> = {
        realtime_destinations: 'Data pipelines',
    }
    const displayProductName = productDisplayNameOverrides[product.type] || product.name

    const upgradeToPlanKey = upgradePlan?.plan_key
    const currentPlanKey = currentPlan?.plan_key

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        700: 'medium',
    })

    // Used when a product is offered for free to beta users, so we want to show usage but
    // there is no pricing (aka tiers) and no free_allotment
    const isTemporaryFreeProduct =
        (!product.tiered && !product.free_allocation && !product.inclusion_only) ||
        (product.tiered && product.tiers?.length === 1 && product.tiers[0].unit_amount_usd === '0')

    // If the feature flag `billing_hide_product_{product.type}` is true,
    // don't show the product in the billing page.
    const hideProductFlag = `billing_hide_product_${product.type}`
    if (featureFlags[hideProductFlag] === true) {
        return null
    }

    return (
        <div
            className={clsx('flex flex-wrap max-w-300 pb-8', {
                'flex-col pb-4': size === 'small',
            })}
            ref={ref}
            data-attr={`billing-product-${product.type}`}
        >
            <div className="border border-primary rounded w-full bg-surface-primary" ref={productRef}>
                <div className="border-b border-primary rounded-t p-4">
                    <div className="flex gap-4 items-center justify-between">
                        {/* Product name and description */}
                        <div className="flex gap-x-2">
                            <div>{getProductIcon(displayProductName, product.icon_key, 'text-2xl shrink-0')}</div>
                            <div>
                                <h3 className="font-bold mb-0 flex items-center gap-x-2">
                                    {displayProductName}{' '}
                                    {isTemporaryFreeProduct && (
                                        <LemonTag type="highlight">included with your plan</LemonTag>
                                    )}
                                    {product.type === 'realtime_destinations' && (
                                        <Tooltip
                                            title={`Data pipelines have moved to new usage-based pricing on ${REALTIME_DESTINATIONS_BILLING_START_DATE}.`}
                                        >
                                            <LemonTag type="success" icon={<IconInfo />}>
                                                Migrated
                                            </LemonTag>
                                        </Tooltip>
                                    )}
                                </h3>
                                <div>{product.description}</div>
                            </div>
                        </div>

                        {/* Product actions */}
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
                                                {billing?.subscription_level === 'custom' &&
                                                    (product.plans?.length > 0 ? (
                                                        <LemonButton
                                                            fullWidth
                                                            onClick={() => {
                                                                setSurveyResponse('$survey_response_1', product.type)
                                                                reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, product.type)
                                                            }}
                                                        >
                                                            Unsubscribe
                                                        </LemonButton>
                                                    ) : (
                                                        <LemonButton
                                                            fullWidth
                                                            to="mailto:sales@posthog.com?subject=Custom%20plan%20unsubscribe%20request"
                                                        >
                                                            Contact support to unsubscribe
                                                        </LemonButton>
                                                    ))}
                                            </>
                                        }
                                    />
                                )
                            )}
                            {surveyID && <UnsubscribeSurveyModal product={product} />}
                        </div>
                    </div>
                </div>
                <div className="px-8 pb-8 sm:pb-0">
                    {/* Exceeded limit notice */}
                    {product.percentage_usage > 1 && (
                        <LemonBanner className="mt-6" type="error">
                            You have exceeded the {hasCustomLimitSet ? 'billing limit' : 'free tier limit'} for this
                            product.
                        </LemonBanner>
                    )}

                    {/* Combined monetary gauge for product variants - only show for subscribed users */}
                    {isProductWithVariants && product.subscribed && (
                        <div className="mt-6 mb-4 ml-2">
                            <div className="grid grid-cols-[1fr_130px_100px] gap-4 items-center">
                                <div>
                                    <BillingGauge
                                        items={combinedMonetaryGaugeItems}
                                        product={{ ...product, unit: '$' }}
                                    />
                                </div>
                                <Tooltip
                                    title={`The current ${
                                        billing?.discount_percent ? 'discounted ' : ''
                                    }amount you have been billed for this ${
                                        billing?.billing_period?.interval
                                    } so far. This number updates once daily.`}
                                >
                                    <div className="flex flex-col items-end">
                                        <div className="font-bold text-3xl leading-7">
                                            {humanFriendlyCurrency(combinedMonetaryData.currentTotal)}
                                        </div>
                                        <span className="text-xs text-secondary whitespace-nowrap">
                                            Month-to-date <IconInfo className="text-muted text-sm" />
                                        </span>
                                    </div>
                                </Tooltip>
                                <Tooltip
                                    title={`This is roughly calculated based on your current bill${
                                        billing?.discount_percent ? ', discounts on your account,' : ''
                                    } and the remaining time left in this billing period. This number updates once daily.${
                                        combinedMonetaryData.billingLimit &&
                                        combinedMonetaryData.projectedTotal >= combinedMonetaryData.billingLimit
                                            ? ` This value is capped at your current billing limit, we will never charge you more than your billing limit.`
                                            : ''
                                    }`}
                                >
                                    <div className="flex flex-col items-end justify-end">
                                        <div className="font-bold text-secondary text-xl">
                                            {humanFriendlyCurrency(combinedMonetaryData.projectedTotal)}
                                        </div>
                                        <span className="text-xs text-secondary whitespace-nowrap">
                                            Projected <IconInfo className="text-muted text-sm" />
                                        </span>
                                    </div>
                                </Tooltip>
                            </div>
                        </div>
                    )}

                    {/* Product variants display */}
                    {productVariants && product.subscribed && !isUnlicensedDebug ? (
                        <div className="space-y-4 mt-4">
                            {productVariants.map(
                                (variant: {
                                    key: string
                                    product: BillingProductV2Type | BillingProductV2AddonType
                                    displayName: string
                                }) => {
                                    const currentAmount = isProductVariantPrimary(variant.key)
                                        ? (product as BillingProductV2Type).current_amount_usd_before_addons || '0'
                                        : (variant.product as BillingProductV2AddonType).current_amount_usd || '0'
                                    const projectedAmount = isProductVariantPrimary(variant.key)
                                        ? projectedAmountExcludingAddons
                                        : variant.product.projected_amount_usd || '0'
                                    const discountMultiplier = 1 - combinedMonetaryData.discountPercent / 100

                                    return (
                                        <div key={variant.key}>
                                            <div className="grid grid-cols-[auto_1fr_130px_100px] gap-4 items-center">
                                                <LemonButton
                                                    icon={
                                                        variantExpandedStates?.[variant.key] ? (
                                                            <IconChevronDown />
                                                        ) : (
                                                            <IconChevronRight />
                                                        )
                                                    }
                                                    size="small"
                                                    onClick={() => toggleVariantExpanded(variant.key)}
                                                />
                                                <h4 className="mb-0 font-bold">{variant.displayName}</h4>
                                                <div className="flex flex-col items-end">
                                                    <span className="font-bold text-lg leading-5">
                                                        {humanFriendlyCurrency(
                                                            parseFloat(currentAmount) * discountMultiplier
                                                        )}
                                                    </span>
                                                    <span className="text-xs text-secondary">Month-to-date</span>
                                                </div>
                                                <div className="flex flex-col items-end">
                                                    <span className="text-secondary text-lg leading-5">
                                                        {humanFriendlyCurrency(
                                                            parseFloat(projectedAmount) * discountMultiplier
                                                        )}
                                                    </span>
                                                    <span className="text-xs text-secondary">Projected</span>
                                                </div>
                                            </div>
                                            {variantExpandedStates?.[variant.key] && (
                                                <div className="mt-4">
                                                    <div className="ml-16">
                                                        <BillingGauge
                                                            items={
                                                                isProductVariantPrimary(variant.key)
                                                                    ? billingGaugeItems
                                                                    : createGaugeItems(variant.product)
                                                            }
                                                            product={variant.product}
                                                        />
                                                    </div>
                                                    <BillingProductPricingTable product={variant.product} />
                                                </div>
                                            )}
                                        </div>
                                    )
                                }
                            )}
                        </div>
                    ) : productVariants && !product.subscribed ? (
                        /* Free user product variants display - simplified like non-variants */
                        <div className="mt-4">
                            {productVariants.map(
                                (variant: {
                                    key: string
                                    product: BillingProductV2Type | BillingProductV2AddonType
                                    displayName: string
                                }) => {
                                    const variantGaugeItems = isProductVariantPrimary(variant.key)
                                        ? billingGaugeItems
                                        : createGaugeItems(variant.product)

                                    return (
                                        <div key={variant.key} className="mt-6">
                                            <h4 className="font-bold">{variant.displayName}</h4>
                                            <div className="sm:flex w-full items-center gap-x-8">
                                                <div className="grow -my-4">
                                                    <BillingGauge items={variantGaugeItems} product={variant.product} />
                                                </div>
                                            </div>
                                        </div>
                                    )
                                }
                            )}
                        </div>
                    ) : (
                        /* Standard product display (non-variants) */
                        <div className="sm:flex w-full items-center gap-x-8">
                            {product.contact_support && (!product.subscribed || isUnlicensedDebug) ? (
                                <div className="py-8">
                                    {!billing?.has_active_subscription && (
                                        <p className="ml-0">
                                            Every product subsciption comes with free platform features such as{' '}
                                            <b>Multiple projects, Integrations, Apps, and more</b>. Subscribe to one of
                                            the products above to get instant access.
                                        </p>
                                    )}
                                    <p className="m-0">
                                        Need additional platform and support (aka enterprise) features like{' '}
                                        <b>SAML SSO</b>, <b>advanced permissioning</b>, and more?{' '}
                                        <Link to="mailto:sales@posthog.com?subject=Enterprise%20plan%20request">
                                            Get in touch
                                        </Link>{' '}
                                        for a quick chat.
                                    </p>
                                </div>
                            ) : (
                                !isUnlicensedDebug && (
                                    <>
                                        {isTemporaryFreeProduct ? (
                                            <div className="grow">
                                                <div className="grow">
                                                    <BillingGauge items={billingGaugeItems} product={product} />
                                                </div>
                                                {/* TODO: rms: remove this notice after August 8 2024 */}
                                                {product.type == ProductKey.DATA_WAREHOUSE &&
                                                    [
                                                        'free-20240530-beta-users-initial',
                                                        'free-20240813-beta-users-initial',
                                                    ].includes(currentPlan?.plan_key || '') &&
                                                    new Date() < new Date('2024-09-04') && (
                                                        <LemonBanner type="info" className="mb-6">
                                                            <p>
                                                                Free usage for beta users until September 2, 2024. Then,
                                                                get 2 million rows free every month.
                                                            </p>
                                                        </LemonBanner>
                                                    )}
                                            </div>
                                        ) : product.tiered ? (
                                            <>
                                                <div className="flex w-full items-center gap-x-8">
                                                    {product.subscribed && (
                                                        <LemonButton
                                                            icon={
                                                                showTierBreakdown ? (
                                                                    <IconChevronDown />
                                                                ) : (
                                                                    <IconChevronRight />
                                                                )
                                                            }
                                                            onClick={() => setShowTierBreakdown(!showTierBreakdown)}
                                                        />
                                                    )}
                                                    <div className="grow">
                                                        <BillingGauge items={billingGaugeItems} product={product} />
                                                    </div>
                                                </div>
                                                {product.subscribed ? (
                                                    <div className="flex justify-end gap-8 flex-wrap items-end shrink-0">
                                                        <Tooltip
                                                            title={`The current ${
                                                                billing?.discount_percent ? 'discounted ' : ''
                                                            }amount you have been billed for this ${
                                                                billing?.billing_period?.interval
                                                            } so far. This number updates once daily.`}
                                                        >
                                                            <div className="flex flex-col items-end">
                                                                <div className="font-bold text-3xl leading-7">
                                                                    {humanFriendlyCurrency(
                                                                        parseFloat(
                                                                            isProductWithVariants
                                                                                ? product.current_amount_usd_before_addons ||
                                                                                      '0'
                                                                                : product.current_amount_usd || '0'
                                                                        ) *
                                                                            (1 -
                                                                                (billing?.discount_percent
                                                                                    ? billing.discount_percent / 100
                                                                                    : 0))
                                                                    )}
                                                                </div>
                                                                <span className="text-xs text-secondary whitespace-nowrap">
                                                                    {capitalizeFirstLetter(
                                                                        billing?.billing_period?.interval || ''
                                                                    )}
                                                                    -to-date <IconInfo className="text-muted text-sm" />
                                                                </span>
                                                            </div>
                                                        </Tooltip>
                                                        {product.tiers && (
                                                            <Tooltip
                                                                title={`This is roughly calculated based on your current bill${
                                                                    billing?.discount_percent
                                                                        ? ', discounts on your account,'
                                                                        : ''
                                                                } and the remaining time left in this billing period. This number updates once daily.${
                                                                    product.projected_amount_usd_with_limit !==
                                                                    product.projected_amount_usd
                                                                        ? ` This value is capped at your current billing limit, we will never charge you more than your billing limit. If you did not have a billing limit set then your projected total would be ${humanFriendlyCurrency(
                                                                              parseFloat(
                                                                                  product.projected_amount_usd || '0'
                                                                              )
                                                                          )}`
                                                                        : ''
                                                                }`}
                                                            >
                                                                <div className="flex flex-col items-end justify-end">
                                                                    <div className="font-bold text-secondary text-lg leading-5">
                                                                        {humanFriendlyCurrency(
                                                                            parseFloat(
                                                                                product.projected_amount_usd_with_limit ||
                                                                                    '0'
                                                                            ) *
                                                                                (1 -
                                                                                    (billing?.discount_percent
                                                                                        ? billing.discount_percent / 100
                                                                                        : 0))
                                                                        )}
                                                                    </div>
                                                                    <span className="text-xs text-secondary whitespace-nowrap">
                                                                        Projected{' '}
                                                                        <IconInfo className="text-muted text-sm" />
                                                                    </span>
                                                                </div>
                                                            </Tooltip>
                                                        )}
                                                    </div>
                                                ) : null}
                                            </>
                                        ) : product.current_amount_usd ? (
                                            <div className="mt-8 mb-4 flex justify-end w-full">
                                                <Tooltip
                                                    title={`The current amount you will be billed for this ${billing?.billing_period?.interval}.`}
                                                >
                                                    <div className="flex flex-col items-center">
                                                        <div className="font-bold text-3xl leading-7">
                                                            {humanFriendlyCurrency(product.current_amount_usd)}
                                                        </div>
                                                        <span className="text-xs text-secondary">
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
                    )}

                    {product.price_description ? (
                        <LemonBanner type="info">
                            <span>{product.price_description}</span>
                        </LemonBanner>
                    ) : null}

                    {/* Table with tiers */}
                    {showTierBreakdown && <BillingProductPricingTable product={product} />}

                    {/* Add-ons (hide for product variants) */}
                    {product.addons?.length > 0 && !isProductWithVariants && (
                        <div className="pb-8">
                            {/* Legacy teams addon */}
                            {product.type === 'platform_and_support' &&
                                product.addons.find((addon) => addon.legacy_product && addon.subscribed) && (
                                    <LemonBanner type="warning" className="my-4" hideIcon>
                                        <p>
                                            You're currently subscribed to our legacy{' '}
                                            {
                                                product.addons.find((addon) => addon.legacy_product && addon.subscribed)
                                                    ?.name
                                            }{' '}
                                            add-on. If you'd like to move to one of our new add-ons please subscribe
                                            below.
                                        </p>
                                    </LemonBanner>
                                )}

                            {/* Add-ons title */}
                            <h4 className="my-4">Add-ons</h4>
                            {billing?.subscription_level == 'free' && (
                                <LemonBanner type="warning" className="text-sm mb-4" hideIcon>
                                    <div className="flex justify-between items-center">
                                        <div>
                                            Add-ons are only available on paid plans. Upgrade to access these features.
                                        </div>
                                        <BillingUpgradeCTA
                                            type="primary"
                                            status="alt"
                                            data-attr="billing-page-addon-cta-upgrade-cta"
                                            disableClientSideRouting
                                            loading={!!billingProductLoading}
                                            onClick={() => startPaymentEntryFlow(product)}
                                        >
                                            Upgrade now
                                        </BillingUpgradeCTA>
                                    </div>
                                </LemonBanner>
                            )}
                            <div className="gap-y-4 flex flex-col">
                                {visibleAddons.map((addon: BillingProductV2AddonType, i: number) => {
                                    return <BillingProductAddon key={i} addon={addon} />
                                })}
                            </div>
                        </div>
                    )}
                </div>

                {/* Billing limit */}
                {!isTemporaryFreeProduct && (
                    <div className={isProductWithVariants ? 'mt-8' : ''}>
                        <BillingLimit product={product} />
                    </div>
                )}

                {/* Feature flag usage notice */}
                <FeatureFlagUsageNotice product={product} />
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

export const FeatureFlagUsageNotice = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    return product.type === 'feature_flags' ? (
        <div className="p-4 px-8 pb-8 sm:pb-0 border-t border-border">
            <p className="mt-0 ml-0 text-sm text-secondary italic">
                <IconInfo className="mr-1" />
                Questions? Here's{' '}
                <Link to="https://posthog.com/docs/feature-flags/common-questions#billing--usage" className="italic">
                    how we calculate usage
                </Link>{' '}
                for feature flags.
            </p>
        </div>
    ) : null
}
