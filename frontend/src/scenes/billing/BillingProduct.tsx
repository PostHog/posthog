import { IconCheckCircle, IconChevronDown, IconDocument, IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { FEATURE_FLAGS, UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, humanFriendlyCurrency } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useRef } from 'react'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType, BillingProductV2Type, BillingTierType, ProductKey } from '~/types'

import { convertLargeNumberToWords, getUpgradeProductLink, summarizeUsage } from './billing-utils'
import { BillingGauge } from './BillingGauge'
import { BillingLimit } from './BillingLimit'
import { billingLogic } from './billingLogic'
import { BillingProductAddon } from './BillingProductAddon'
import { billingProductLogic } from './billingProductLogic'
import { BillingProductPricingTable } from './BillingProductPricingTable'
import { PlanComparisonModal } from './PlanComparison'
import { ProductPricingModal } from './ProductPricingModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

export const getTierDescription = (
    tiers: BillingTierType[],
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
    const { billing, redirectPath, isUnlicensedDebug, billingError } = useValues(billingLogic)
    const {
        hasCustomLimitSet,
        showTierBreakdown,
        billingGaugeItems,
        isPricingModalOpen,
        isPlanComparisonModalOpen,
        currentAndUpgradePlans,
        surveyID,
        billingProductLoading,
    } = useValues(billingProductLogic({ product }))
    const {
        setShowTierBreakdown,
        toggleIsPricingModalOpen,
        toggleIsPlanComparisonModalOpen,
        reportSurveyShown,
        setSurveyResponse,
        setBillingProductLoading,
    } = useActions(billingProductLogic({ product, productRef }))
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { upgradePlan, currentPlan, downgradePlan } = currentAndUpgradePlans
    const additionalFeaturesOnUpgradedPlan = upgradePlan
        ? upgradePlan?.features?.filter(
              (feature) =>
                  !currentPlan?.features?.some((currentPlanFeature) => currentPlanFeature.name === feature.name)
          )
        : currentPlan?.features?.filter(
              (feature) =>
                  !downgradePlan?.features?.some((downgradePlanFeature) => downgradePlanFeature.name === feature.name)
          ) || []

    const upgradeToPlanKey = upgradePlan?.plan_key
    const currentPlanKey = currentPlan?.plan_key

    // Note(@zach): The upgrade card will be removed when Subscribe to all products is fully rolled out
    const showUpgradeCard =
        (upgradePlan?.product_key !== 'platform_and_support' || product?.addons?.length === 0) &&
        upgradePlan &&
        billing?.subscription_level === 'custom'

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        700: 'medium',
    })

    // Used when a product is offered for free to beta users, so we want to show usage but
    // there is no pricing (aka tiers) and no free_allotment
    const isTemporaryFreeProduct =
        (!product.tiered && !product.free_allocation && !product.inclusion_only) ||
        (product.tiered && product.tiers?.length === 1 && product.tiers[0].unit_amount_usd === '0')

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
                            <h3 className="font-bold mb-0 flex items-center gap-x-2">
                                {product.name}{' '}
                                {isTemporaryFreeProduct && (
                                    <LemonTag type="highlight">included with your plan</LemonTag>
                                )}
                            </h3>
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
                    {product.percentage_usage > 1 && (
                        <LemonBanner className="mt-6" type="error">
                            You have exceeded the {hasCustomLimitSet ? 'billing limit' : 'free tier limit'} for this
                            product.
                        </LemonBanner>
                    )}
                    <div className="sm:flex w-full items-center gap-x-8">
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
                                    {isTemporaryFreeProduct ? (
                                        <div className="grow">
                                            <div className="grow">
                                                <BillingGauge items={billingGaugeItems} product={product} />
                                                <FeatureFlagUsageNotice product={product} />
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
                                                            Free usage for beta users until September 2, 2024. Then, get
                                                            2 million rows free every month.
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
                                                    {!product.subscribed && (
                                                        <FeatureFlagUsageNotice product={product} />
                                                    )}
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
                                                        <div className="flex flex-col items-center">
                                                            <div className="font-bold text-3xl leading-7">
                                                                $
                                                                {humanFriendlyCurrency(
                                                                    parseFloat(product.current_amount_usd || '0') *
                                                                        (1 -
                                                                            (billing?.discount_percent
                                                                                ? billing.discount_percent / 100
                                                                                : 0))
                                                                )}
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
                                                                    {humanFriendlyCurrency(
                                                                        parseFloat(
                                                                            product.projected_amount_usd || '0'
                                                                        ) *
                                                                            (1 -
                                                                                (billing?.discount_percent
                                                                                    ? billing.discount_percent / 100
                                                                                    : 0))
                                                                    )}
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
                                                        ${humanFriendlyCurrency(product.current_amount_usd)}
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
                {!isTemporaryFreeProduct && <BillingLimit product={product} />}
                {showUpgradeCard && (
                    <div
                        data-attr={`upgrade-card-${product.type}`}
                        className={`border-t border-border p-8 flex justify-between ${
                            !upgradePlan ? 'bg-success-highlight' : 'bg-warning-highlight'
                        }`}
                    >
                        <div>
                            {currentPlan && (
                                <h4 className={`${!upgradePlan ? 'text-success' : 'text-warning-dark'}`}>
                                    You're on the {currentPlan.name} plan for {product.name}.
                                </h4>
                            )}
                            {additionalFeaturesOnUpgradedPlan?.length > 0 ? (
                                <>
                                    <p className="ml-0 max-w-200">Subscribe to get sweet features such as:</p>
                                    <div>
                                        {additionalFeaturesOnUpgradedPlan?.map((feature, i) => {
                                            return (
                                                i < 3 && (
                                                    <div
                                                        className="flex gap-x-2 items-center mb-2"
                                                        key={'additional-features-' + product.type + i}
                                                    >
                                                        <IconCheckCircle className="text-success" />
                                                        <Tooltip key={feature.key} title={feature.description}>
                                                            <b>{feature.name} </b>
                                                        </Tooltip>
                                                    </div>
                                                )
                                            )
                                        })}
                                        {!billing?.has_active_subscription && (
                                            <div className="flex gap-x-2 items-center mb-2">
                                                <IconCheckCircle className="text-success" />
                                                <Tooltip title="Multiple projects, Feature flags, Experiments, Integrations, Apps, and more">
                                                    <b>Upgraded platform features</b>
                                                </Tooltip>
                                            </div>
                                        )}
                                        <div className="flex gap-x-2 items-center mb-2">
                                            <IconCheckCircle className="text-success" />
                                            <Link onClick={() => toggleIsPlanComparisonModalOpen()}>
                                                <b>And more...</b>
                                            </Link>
                                        </div>
                                    </div>
                                </>
                            ) : (
                                <p className="ml-0 max-w-200">
                                    You've got access to all the features we offer for {product.name}.
                                </p>
                            )}
                            {upgradePlan?.tiers?.[0]?.unit_amount_usd &&
                                parseInt(upgradePlan?.tiers?.[0].unit_amount_usd) === 0 && (
                                    <p className="ml-0 mb-0 mt-4">
                                        <b>
                                            First {convertLargeNumberToWords(upgradePlan?.tiers?.[0].up_to, null)}{' '}
                                            {product.unit}s free
                                        </b>
                                        , then just ${upgradePlan?.tiers?.[1]?.unit_amount_usd} per {product.unit} and{' '}
                                        <Link onClick={() => toggleIsPlanComparisonModalOpen()}>volume discounts</Link>.
                                    </p>
                                )}
                        </div>
                        {upgradePlan && (
                            <div className="ml-4">
                                <div className="flex flex-wrap gap-x-2 gap-y-2">
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => toggleIsPlanComparisonModalOpen()}
                                        className="grow"
                                        center
                                    >
                                        Compare plans
                                    </LemonButton>
                                    {upgradePlan.contact_support ? (
                                        <LemonButton
                                            type="primary"
                                            to="mailto:sales@posthog.com?subject=Enterprise%20plan%20request"
                                        >
                                            Get in touch
                                        </LemonButton>
                                    ) : (
                                        upgradePlan.included_if !== 'has_subscription' &&
                                        !upgradePlan.unit_amount_usd && (
                                            <BillingUpgradeCTA
                                                data-attr={`${product.type}-upgrade-cta`}
                                                to={getUpgradeProductLink({
                                                    product,
                                                    redirectPath,
                                                    includeAddons: false,
                                                })}
                                                type="primary"
                                                icon={<IconPlus />}
                                                disableClientSideRouting
                                                loading={billingProductLoading === product.type}
                                                disabledReason={billingError && billingError.message}
                                                onClick={() => {
                                                    reportBillingUpgradeClicked(product.type)
                                                    setBillingProductLoading(product.type)
                                                }}
                                                className="grow"
                                                center
                                            >
                                                Subscribe
                                            </BillingUpgradeCTA>
                                        )
                                    )}
                                </div>
                            </div>
                        )}
                        <PlanComparisonModal
                            product={product}
                            includeAddons={false}
                            modalOpen={isPlanComparisonModalOpen}
                            onClose={() => toggleIsPlanComparisonModalOpen()}
                        />
                    </div>
                )}
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
        <p className="mt-4 ml-0 text-sm text-muted italic">
            <IconInfo className="mr-1" />
            Questions? Here's{' '}
            <Link to="https://posthog.com/docs/feature-flags/common-questions#billing--usage" className="italic">
                how we calculate usage
            </Link>{' '}
            for feature flags.
        </p>
    ) : null
}
