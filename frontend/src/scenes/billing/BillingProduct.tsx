import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSelectOptions, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import {
    IconArticle,
    IconCheckCircleOutline,
    IconCheckmark,
    IconChevronRight,
    IconExpandMore,
    IconInfo,
} from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, compactNumber } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'
import { useRef } from 'react'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType, BillingProductV2Type, BillingV2TierType } from '~/types'

import { convertLargeNumberToWords, getUpgradeProductLink, summarizeUsage } from './billing-utils'
import { BillingGauge } from './BillingGauge'
import { BillingLimitInput } from './BillingLimitInput'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { PlanComparisonModal } from './PlanComparison'
import { ProductPricingModal } from './ProductPricingModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

const UNSUBSCRIBE_SURVEY_ID = '018b6e13-590c-0000-decb-c727a2b3f462'

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

export const BillingProductAddon = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { billing, redirectPath } = useValues(billingLogic)
    const { isPricingModalOpen, currentAndUpgradePlans, surveyID } = useValues(billingProductLogic({ product: addon }))
    const { toggleIsPricingModalOpen, reportSurveyShown, setSurveyResponse } = useActions(
        billingProductLogic({ product: addon })
    )
    const { featureFlags } = useValues(featureFlagLogic)
    const { setProductSpecificAlert } = useActions(billingLogic)

    const productType = { plural: `${addon.unit}s`, singular: addon.unit }
    const tierDisplayOptions: LemonSelectOptions<string> = [
        { label: `Per ${productType.singular}`, value: 'individual' },
    ]

    if (billing?.has_active_subscription) {
        tierDisplayOptions.push({ label: `Current bill`, value: 'total' })
    }

    const isOGPipelineAddon =
        addon.type === 'data_pipelines' &&
        addon.subscribed &&
        addon.plans?.[0]?.plan_key === 'addon-20240111-og-customers'

    if (isOGPipelineAddon && featureFlags['data-pipelines-notice']) {
        setProductSpecificAlert({
            status: 'info',
            title: 'Welcome to the data pipelines addon!',
            message: `We've moved data export features (and cost) here to better reflect user needs. Your overall
                    price hasn't changed.`,
            action: {
                onClick: () => {
                    posthog.capture('data pipelines notice clicked')
                    // if they don't dismiss it now, we won't show it next time they come back
                    posthog.capture('data pipelines notice dismissed', {
                        $set: {
                            dismissedDataPipelinesNotice: true,
                        },
                    })
                },
                children: 'Learn more',
                to: 'https://posthog.com/changelog/2024#data-pipeline-add-on-launched',
                targetBlank: true,
            },
            dismissKey: 'data-pipelines-notice',
            onClose: () => {
                posthog.capture('data pipelines notice dismissed', {
                    $set: {
                        dismissedDataPipelinesNotice: true,
                    },
                })
            },
        })
    }
    return (
        <div className="bg-side rounded p-6 flex flex-col">
            <div className="flex justify-between gap-x-4">
                <div className="flex gap-x-4">
                    <div className="w-8">{getProductIcon(addon.name, addon.icon_key, 'text-2xl')}</div>
                    <div>
                        <div className="flex gap-x-2 items-center mt-0 mb-2 ">
                            <h4 className="leading-5 mb-1 font-bold">{addon.name}</h4>
                            {addon.subscribed && (
                                <div>
                                    <LemonTag type="primary" icon={<IconCheckmark />}>
                                        Subscribed
                                    </LemonTag>
                                </div>
                            )}
                        </div>
                        <p className="ml-0 mb-0">{addon.description}</p>
                        {isOGPipelineAddon && (
                            <div className="mt-2">
                                <Link
                                    targetBlankIcon
                                    target="_blank"
                                    to="https://posthog.com/changelog/2024#data-pipeline-add-on-launched"
                                >
                                    <span className="text-xs italic">Why am I subscribed to this?</span>
                                </Link>
                            </div>
                        )}
                    </div>
                </div>
                <div className="ml-4 mr-4 mt-2 self-center flex gap-x-2 whitespace-nowrap">
                    {addon.docs_url && (
                        <Tooltip title="Read the docs">
                            <LemonButton icon={<IconArticle />} size="small" to={addon.docs_url} />
                        </Tooltip>
                    )}
                    {addon.subscribed ? (
                        <>
                            <More
                                overlay={
                                    <>
                                        <LemonButton
                                            fullWidth
                                            onClick={() => {
                                                setSurveyResponse(addon.type, '$survey_response_1')
                                                reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, addon.type)
                                            }}
                                        >
                                            Remove addon
                                        </LemonButton>
                                    </>
                                }
                            />
                        </>
                    ) : addon.included_with_main_product ? (
                        <LemonTag type="completion" icon={<IconCheckmark />}>
                            Included with plan
                        </LemonTag>
                    ) : (
                        <>
                            <LemonButton
                                type="secondary"
                                disableClientSideRouting
                                onClick={() => {
                                    toggleIsPricingModalOpen()
                                }}
                            >
                                View pricing
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                size="small"
                                to={`/api/billing-v2/activation?products=${addon.type}:${
                                    currentAndUpgradePlans?.upgradePlan?.plan_key
                                }${redirectPath && `&redirect_path=${redirectPath}`}`}
                                disableClientSideRouting
                            >
                                Add
                            </LemonButton>
                        </>
                    )}
                </div>
            </div>
            <ProductPricingModal
                modalOpen={isPricingModalOpen}
                onClose={toggleIsPricingModalOpen}
                product={addon}
                planKey={
                    addon.subscribed
                        ? currentAndUpgradePlans?.currentPlan?.plan_key
                        : currentAndUpgradePlans?.upgradePlan?.plan_key
                }
            />
            {surveyID && <UnsubscribeSurveyModal product={addon} />}
        </div>
    )
}

export const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const productRef = useRef<HTMLDivElement | null>(null)
    const { billing, redirectPath, isOnboarding, isUnlicensedDebug } = useValues(billingLogic)
    const {
        customLimitUsd,
        showTierBreakdown,
        billingGaugeItems,
        isPricingModalOpen,
        isPlanComparisonModalOpen,
        currentAndUpgradePlans,
        surveyID,
    } = useValues(billingProductLogic({ product }))
    const {
        setIsEditingBillingLimit,
        setShowTierBreakdown,
        toggleIsPricingModalOpen,
        toggleIsPlanComparisonModalOpen,
        reportSurveyShown,
        setSurveyResponse,
    } = useActions(billingProductLogic({ product, productRef }))
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)

    const showUpgradeCTA = !product.subscribed && !product.contact_support && product.plans?.length
    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    const currentPlan = currentAndUpgradePlans?.currentPlan
    const downgradePlan = currentAndUpgradePlans?.downgradePlan
    const additionalFeaturesOnUpgradedPlan = upgradePlan
        ? upgradePlan?.features?.filter(
              (feature) =>
                  !currentPlan?.features?.some((currentPlanFeature) => currentPlanFeature.name === feature.name)
          )
        : currentPlan?.features?.filter(
              (feature) =>
                  !downgradePlan?.features?.some((downgradePlanFeature) => downgradePlanFeature.name === feature.name)
          )

    const upgradeToPlanKey = upgradePlan?.plan_key
    const currentPlanKey = currentPlan?.plan_key

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        700: 'medium',
    })

    const addonPriceColumns = product.addons
        // only get addons that are subscribed or were subscribed and have a projected amount
        ?.filter((addon) => addon.subscribed || parseFloat(addon.projected_amount_usd || ''))
        .map((addon) => ({
            title: `${addon.name} price`,
            dataIndex: `${addon.type}-price`,
        }))

    const tableColumns = [
        { title: `Priced per ${product.unit}`, dataIndex: 'volume' },
        { title: addonPriceColumns?.length > 0 ? 'Base price' : 'Price', dataIndex: 'basePrice' },
        ...(addonPriceColumns || []),
        { title: 'Current Usage', dataIndex: 'usage' },
        { title: 'Total', dataIndex: 'total' },
        { title: 'Projected Total', dataIndex: 'projectedTotal' },
    ]

    type TableTierDatum = {
        volume: string
        basePrice: string
        [addonPrice: string]: string
        usage: string
        total: string
        projectedTotal: string
    }

    // TODO: SUPPORT NON-TIERED PRODUCT TYPES
    // still use the table, but the data will be different
    const tableTierData: TableTierDatum[] | undefined =
        product.tiers && product.tiers.length > 0
            ? product.tiers
                  ?.map((tier, i) => {
                      const addonPricesForTier = product.addons?.map((addon) => ({
                          [`${addon.type}-price`]: `${
                              addon.tiers?.[i]?.unit_amount_usd !== '0'
                                  ? '$' + addon.tiers?.[i]?.unit_amount_usd
                                  : 'Free'
                          }`,
                      }))
                      // take the tier.current_amount_usd and add it to the same tier level for all the addons
                      const totalForTier =
                          parseFloat(tier.current_amount_usd || '') +
                          (product.addons?.reduce(
                              (acc, addon) => acc + parseFloat(addon.tiers?.[i]?.current_amount_usd || ''),
                              0
                              // if there aren't any addons we get NaN from the above, so we need to default to 0
                          ) || 0)
                      const projectedTotalForTier =
                          (parseFloat(tier.projected_amount_usd || '') || 0) +
                          product.addons?.reduce(
                              (acc, addon) => acc + (parseFloat(addon.tiers?.[i]?.projected_amount_usd || '') || 0),
                              0
                          )

                      const tierData = {
                          volume: product.tiers // this is silly because we know there are tiers since we check above, but typescript doesn't
                              ? getTierDescription(product.tiers, i, product, billing?.billing_period?.interval || '')
                              : '',
                          basePrice: tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free',
                          usage: compactNumber(tier.current_usage),
                          total: `$${totalForTier.toFixed(2) || '0.00'}`,
                          projectedTotal: `$${projectedTotalForTier.toFixed(2) || '0.00'}`,
                      }
                      // if there are any addon prices we need to include, put them in the table
                      addonPricesForTier?.map((addonPrice) => {
                          Object.assign(tierData, addonPrice)
                      })
                      return tierData
                  })
                  // Add a row at the end for the total
                  .concat({
                      volume: 'Total',
                      basePrice: '',
                      usage: '',
                      total: `$${product.current_amount_usd || '0.00'}`,
                      projectedTotal: `$${product.projected_amount_usd || '0.00'}`,
                  })
            : undefined

    if (billing?.discount_percent && parseFloat(product.projected_amount_usd || '')) {
        // If there is a discount, add a row for the total after discount if there is also a projected amount
        tableTierData?.push({
            volume: 'Total after discount',
            basePrice: '',
            usage: '',
            total: `$${
                (parseInt(product.current_amount_usd || '0') * (1 - billing?.discount_percent / 100)).toFixed(2) ||
                '0.00'
            }`,
            projectedTotal: `$${
                (
                    parseInt(product.projected_amount_usd || '0') -
                    parseInt(product.projected_amount_usd || '0') * (billing?.discount_percent / 100)
                ).toFixed(2) || '0.00'
            }`,
        })
    }

    return (
        <div
            className={clsx('flex flex-wrap max-w-300 pb-12', {
                'flex-col pb-4': size === 'small',
            })}
            ref={ref}
        >
            <div className="border border-border rounded w-full bg-bg-light" ref={productRef}>
                <div className="border-b border-border bg-mid p-4">
                    <div className="flex gap-4 items-center justify-between">
                        {getProductIcon(product.name, product.icon_key, 'text-2xl')}
                        <div>
                            <h3 className="font-bold mb-0">{product.name}</h3>
                            <div>{product.description}</div>
                        </div>
                        <div className="flex grow justify-end gap-x-2 items-center">
                            {product.docs_url && (
                                <Tooltip title="Read the docs">
                                    <LemonButton
                                        icon={<IconArticle />}
                                        size="small"
                                        to={product.docs_url}
                                        className="justify-end"
                                    />
                                </Tooltip>
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
                                                {billing?.billing_period?.interval == 'month' && (
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => setIsEditingBillingLimit(true)}
                                                    >
                                                        Set billing limit
                                                    </LemonButton>
                                                )}
                                                <LemonButton
                                                    fullWidth
                                                    to="https://posthog.com/docs/billing/estimating-usage-costs#how-to-reduce-your-posthog-costs"
                                                >
                                                    Learn how to reduce your bill
                                                </LemonButton>
                                                {product.plans?.length > 0 ? (
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => {
                                                            setSurveyResponse(product.type, '$survey_response_1')
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
                                                )}
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
                    {product.percentage_usage > 1 ? (
                        <LemonBanner type="error">
                            You have exceeded the {customLimitUsd ? 'billing limit' : 'free tier limit'} for this
                            product.
                        </LemonBanner>
                    ) : null}
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
                            !isOnboarding &&
                            !isUnlicensedDebug && (
                                <>
                                    {product.tiered ? (
                                        <>
                                            {product.subscribed && (
                                                <LemonButton
                                                    icon={showTierBreakdown ? <IconExpandMore /> : <IconChevronRight />}
                                                    onClick={() => setShowTierBreakdown(!showTierBreakdown)}
                                                />
                                            )}
                                            <div className="grow">
                                                <BillingGauge items={billingGaugeItems} product={product} />
                                            </div>
                                            {product.current_amount_usd ? (
                                                <div className="flex justify-end gap-8 flex-wrap items-end">
                                                    <Tooltip
                                                        title={`The current ${
                                                            billing?.discount_percent ? 'discounted ' : ''
                                                        }amount you have been billed for this ${
                                                            billing?.billing_period?.interval
                                                        } so far.`}
                                                        className="flex flex-col items-center"
                                                    >
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
                                                    </Tooltip>
                                                    {product.tiers && (
                                                        <Tooltip
                                                            title={`This is roughly calculated based on your current bill${
                                                                billing?.discount_percent
                                                                    ? ', discounts on your account,'
                                                                    : ''
                                                            } and the remaining time left in this billing period.`}
                                                            className="flex flex-col items-center justify-end"
                                                        >
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
                                                        </Tooltip>
                                                    )}
                                                </div>
                                            ) : null}
                                        </>
                                    ) : (
                                        <div className="my-8">
                                            <Tooltip
                                                title={`The current amount you will be billed for this ${billing?.billing_period?.interval}.`}
                                                className="flex flex-col items-center"
                                            >
                                                <div className="font-bold text-3xl leading-7">
                                                    ${product.current_amount_usd}
                                                </div>
                                                <span className="text-xs text-muted">
                                                    per {billing?.billing_period?.interval || 'period'}
                                                </span>
                                            </Tooltip>
                                        </div>
                                    )}
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
                    {showTierBreakdown && (
                        <div className="pl-16 pb-8">
                            {product.tiered && tableTierData ? (
                                <>
                                    <LemonTable
                                        stealth
                                        embedded
                                        size="small"
                                        uppercaseHeader={false}
                                        columns={tableColumns}
                                        dataSource={tableTierData}
                                    />
                                    {product.type === 'feature_flags' && (
                                        <p className="mt-4 ml-0 text-sm text-muted italic">
                                            <IconInfo className="mr-1" />
                                            Using local evaluation? Here's{' '}
                                            <Link
                                                to="https://posthog.com/docs/feature-flags/bootstrapping-and-local-evaluation#server-side-local-evaluation"
                                                className="italic"
                                            >
                                                how we calculate usage
                                            </Link>
                                            .
                                        </p>
                                    )}
                                </>
                            ) : (
                                <LemonTable
                                    stealth
                                    embedded
                                    size="small"
                                    uppercaseHeader={false}
                                    columns={[
                                        { title: '', dataIndex: 'name' },
                                        { title: 'Total', dataIndex: 'total' },
                                    ]}
                                    dataSource={[
                                        {
                                            name: product.name,
                                            total: product.unit_amount_usd,
                                        },
                                    ]}
                                />
                            )}
                        </div>
                    )}
                    {!isOnboarding && product.addons?.length > 0 && (
                        <div className="pb-8">
                            <h4 className="my-4">Addons</h4>
                            <div className="gap-y-4 flex flex-col">
                                {product.addons.map((addon, i) => {
                                    return <BillingProductAddon key={i} addon={addon} />
                                })}
                            </div>
                        </div>
                    )}
                </div>
                {(showUpgradeCTA || (isOnboarding && !product.contact_support)) && (
                    <div
                        data-attr={`upgrade-card-${product.type}`}
                        className={`border-t border-border p-8 flex justify-between ${
                            product.subscribed ? 'bg-success-highlight' : 'bg-warning-highlight'
                        }`}
                    >
                        <div>
                            <h4 className={`${product.subscribed ? 'text-success-dark' : 'text-warning-dark'}`}>
                                You're on the {product.subscribed ? 'paid' : 'free'} plan for {product.name}.
                            </h4>
                            {additionalFeaturesOnUpgradedPlan?.length > 0 ? (
                                <>
                                    <p className="ml-0 max-w-200">
                                        {product.subscribed ? 'You now' : 'Upgrade to'} get sweet features such as:
                                    </p>
                                    <div>
                                        {additionalFeaturesOnUpgradedPlan?.map((feature, i) => {
                                            return (
                                                i < 3 && (
                                                    <div
                                                        className="flex gap-x-2 items-center mb-2"
                                                        key={'additional-features-' + product.type + i}
                                                    >
                                                        <IconCheckCircleOutline className="text-success" />
                                                        <Tooltip key={feature.key} title={feature.description}>
                                                            <b>{feature.name} </b>
                                                        </Tooltip>
                                                    </div>
                                                )
                                            )
                                        })}
                                        {!billing?.has_active_subscription && (
                                            <div className="flex gap-x-2 items-center mb-2">
                                                <IconCheckCircleOutline className="text-success" />
                                                <Tooltip title="Multiple projects, Feature flags, Experiments, Integrations, Apps, and more">
                                                    <b>Upgraded platform features</b>
                                                </Tooltip>
                                            </div>
                                        )}
                                        <div className="flex gap-x-2 items-center mb-2">
                                            <IconCheckCircleOutline className="text-success" />
                                            {product.subscribed ? (
                                                <b>And more</b>
                                            ) : (
                                                <Link onClick={toggleIsPlanComparisonModalOpen}>
                                                    <b>And more...</b>
                                                </Link>
                                            )}
                                        </div>
                                    </div>
                                </>
                            ) : (
                                <p className="ml-0 max-w-200">
                                    You've got access to all the features we offer for {product.name}.
                                </p>
                            )}
                            {upgradePlan?.tiers?.[0].unit_amount_usd &&
                                parseInt(upgradePlan?.tiers?.[0].unit_amount_usd) === 0 && (
                                    <p className="ml-0 mb-0 mt-4">
                                        <b>
                                            First {convertLargeNumberToWords(upgradePlan?.tiers?.[0].up_to, null)}{' '}
                                            {product.unit}s free
                                        </b>
                                        , then ${upgradePlan?.tiers?.[1]?.unit_amount_usd}/{product.unit} with volume
                                        discounts.
                                    </p>
                                )}
                        </div>
                        {!product.subscribed && (
                            <div className="ml-4">
                                <div className="flex flex-wrap gap-x-2 gap-y-2">
                                    <LemonButton
                                        type="secondary"
                                        onClick={toggleIsPlanComparisonModalOpen}
                                        className="grow"
                                        center
                                    >
                                        Compare plans
                                    </LemonButton>
                                    <LemonButton
                                        to={getUpgradeProductLink(
                                            product,
                                            upgradeToPlanKey || '',
                                            redirectPath,
                                            isOnboarding // if in onboarding, we want to include addons, otherwise don't
                                        )}
                                        type="primary"
                                        icon={<IconPlus />}
                                        disableClientSideRouting
                                        onClick={() => {
                                            reportBillingUpgradeClicked(product.type)
                                        }}
                                        className="grow"
                                        center
                                    >
                                        Upgrade
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                        <PlanComparisonModal
                            product={product}
                            includeAddons={isOnboarding}
                            modalOpen={isPlanComparisonModalOpen}
                            onClose={toggleIsPlanComparisonModalOpen}
                        />
                    </div>
                )}
                <BillingLimitInput product={product} />
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
