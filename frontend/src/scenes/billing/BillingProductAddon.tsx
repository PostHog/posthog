import { IconCheckCircle, IconPlus } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelectOptions, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS, UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyCurrency, toSentenceCase } from 'lib/utils'
import { ReactNode, useMemo, useRef } from 'react'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType } from '~/types'

import { getProration } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { ProductPricingModal } from './ProductPricingModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

const formatFlatRate = (flatRate: number, unit: string | null): string | ReactNode => {
    if (!unit) {
        return `$${flatRate}`
    }
    return (
        <span className="space-x-0.5">
            <span>{humanFriendlyCurrency(flatRate)}</span>
            <span>/</span>
            <span>{unit}</span>
        </span>
    )
}

export const BillingProductAddon = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const productRef = useRef<HTMLDivElement | null>(null)
    const { billing, redirectPath, billingError, timeTotalInSeconds, timeRemainingInSeconds } = useValues(billingLogic)
    const {
        isPricingModalOpen,
        currentAndUpgradePlans,
        surveyID,
        billingProductLoading,
        trialModalOpen,
        trialLoading,
    } = useValues(billingProductLogic({ product: addon, productRef }))
    const {
        toggleIsPricingModalOpen,
        reportSurveyShown,
        setSurveyResponse,
        initiateProductUpgrade,
        setTrialModalOpen,
        activateTrial,
    } = useActions(billingProductLogic({ product: addon }))
    const { openSupportForm } = useActions(supportLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    const upgradePlan = currentAndUpgradePlans?.upgradePlan

    const { prorationAmount, isProrated } = useMemo(
        () =>
            getProration({
                timeRemainingInSeconds,
                timeTotalInSeconds,
                amountUsd: upgradePlan?.unit_amount_usd,
                hasActiveSubscription: billing?.has_active_subscription,
            }),
        [billing?.has_active_subscription, upgradePlan, timeRemainingInSeconds, timeTotalInSeconds]
    )

    const productType = { plural: `${addon.unit}s`, singular: addon.unit }
    const tierDisplayOptions: LemonSelectOptions<string> = [
        { label: `Per ${productType.singular}`, value: 'individual' },
    ]

    if (billing?.has_active_subscription) {
        tierDisplayOptions.push({ label: `Current bill`, value: 'total' })
    }

    // Filter out the addon itself from the features list
    const addonFeatures =
        currentAndUpgradePlans?.upgradePlan?.features ||
        currentAndUpgradePlans?.currentPlan?.features ||
        addon.features?.filter((feature) => feature.name !== addon.name)

    const is_enhanced_persons_og_customer =
        addon.type === 'enhanced_persons' &&
        addon.plans?.find((plan) => plan.plan_key === 'addon-20240404-og-customers')

    const trialExperiment = featureFlags[FEATURE_FLAGS.BILLING_TRIAL_FLOW]

    const handleTrialActivation = (): void => {
        if (trialExperiment === 'modal') {
            // Modal - Show trial modal (default behavior)
            setTrialModalOpen(true)
        } else if (trialExperiment === 'control') {
            // Direct - Activate trial immediately
            activateTrial()
        } else {
            // No trial flow even without the feature flag
            initiateProductUpgrade(addon, currentAndUpgradePlans?.upgradePlan, redirectPath)
        }
    }

    return (
        <div
            className="bg-bg-3000 rounded p-6 flex flex-col"
            ref={productRef}
            data-attr={`billing-product-addon-${addon.type}`}
        >
            <div className="sm:flex justify-between gap-x-4">
                <div className="flex gap-x-4">
                    <div className="w-8">{getProductIcon(addon.name, addon.icon_key, 'text-2xl')}</div>
                    <div>
                        <div className="flex gap-x-2 items-center mt-0 mb-2 ">
                            <h4 className="leading-5 mb-1 font-bold">{addon.name}</h4>
                            {addon.inclusion_only ? (
                                <div className="flex gap-x-2">
                                    <Tooltip title="Automatically included with your plan. Used based on your posthog-js config options.">
                                        <LemonTag type="muted">Config option</LemonTag>
                                    </Tooltip>
                                </div>
                            ) : (
                                addon.subscribed && (
                                    <div>
                                        <LemonTag type="primary" icon={<IconCheckCircle />}>
                                            Subscribed
                                        </LemonTag>
                                    </div>
                                )
                            )}
                        </div>
                        <p className="ml-0 mb-0">
                            {addon.description}{' '}
                            {addon.docs_url && (
                                <>
                                    <Link to={addon.docs_url}>Read the docs</Link> for more information.
                                </>
                            )}
                        </p>
                        {is_enhanced_persons_og_customer && (
                            <p className="mt-2 mb-0">
                                <Link
                                    to="https://posthog.com/changelog/2024#person-profiles-launched-posthog-now-up-to-80percent-cheaper"
                                    className="italic"
                                    target="_blank"
                                    targetBlankIcon
                                >
                                    Why is this here?{' '}
                                </Link>
                            </p>
                        )}
                    </div>
                </div>
                <div className="min-w-64">
                    <div className="ml-4 mt-2 self-center flex items-center justify-end gap-x-3 whitespace-nowrap">
                        {addon.subscribed && !addon.inclusion_only ? (
                            !addon.contact_support && (
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                fullWidth
                                                onClick={() => {
                                                    setSurveyResponse('$survey_response_1', addon.type)
                                                    reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, addon.type)
                                                }}
                                            >
                                                Remove add-on
                                            </LemonButton>
                                        </>
                                    }
                                />
                            )
                        ) : billing?.trial?.target === addon.type ? (
                            <div className="flex flex-col items-end justify-end">
                                <Tooltip
                                    title={
                                        <p>
                                            You are currently on a free trial for{' '}
                                            <b>{toSentenceCase(billing.trial.target)}</b> until{' '}
                                            <b>{dayjs(billing.trial.expires_at).format('LL')}</b>. At the end of the
                                            trial{' '}
                                            {billing.trial.type === 'autosubscribe'
                                                ? 'you will be automatically subscribed to the plan.'
                                                : 'you will be asked to subscribe. If you choose not to, you will lose access to the features.'}
                                        </p>
                                    }
                                >
                                    <LemonTag type="completion" icon={<IconCheckCircle />}>
                                        You're on a trial for this add-on
                                    </LemonTag>
                                </Tooltip>
                                {/* Comment out until we can make sure a customer can't activate a trial multiple times */}
                                {/* <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={cancelTrial}
                                    loading={trialLoading}
                                    className="mt-1"
                                >
                                    Cancel trial
                                </LemonButton> */}
                            </div>
                        ) : addon.included_with_main_product ? (
                            <LemonTag type="completion" icon={<IconCheckCircle />}>
                                Included with plan
                            </LemonTag>
                        ) : addon.contact_support ? (
                            <LemonButton type="secondary" to="https://posthog.com/talk-to-a-human">
                                Contact support
                            </LemonButton>
                        ) : (
                            <>
                                {currentAndUpgradePlans?.upgradePlan?.flat_rate ? (
                                    <h4 className="leading-5 font-bold mb-0 space-x-0.5">
                                        {addon.trial && !!trialExperiment ? (
                                            <span>{addon.trial.length} day free trial</span>
                                        ) : (
                                            <span>
                                                {formatFlatRate(
                                                    Number(upgradePlan?.unit_amount_usd),
                                                    upgradePlan?.unit
                                                )}
                                            </span>
                                        )}
                                    </h4>
                                ) : (
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => {
                                            toggleIsPricingModalOpen()
                                        }}
                                    >
                                        View pricing
                                    </LemonButton>
                                )}
                                {!addon.inclusion_only &&
                                    (addon.trial && !!trialExperiment ? (
                                        <LemonButton
                                            type="primary"
                                            icon={<IconPlus />}
                                            size="small"
                                            disableClientSideRouting
                                            disabledReason={
                                                (billingError && billingError.message) ||
                                                (billing?.subscription_level === 'free' && 'Upgrade to add add-ons')
                                            }
                                            loading={billingProductLoading === addon.type}
                                            onClick={handleTrialActivation}
                                        >
                                            Start trial
                                        </LemonButton>
                                    ) : (
                                        <LemonButton
                                            type="primary"
                                            icon={<IconPlus />}
                                            size="small"
                                            disableClientSideRouting
                                            disabledReason={
                                                (billingError && billingError.message) ||
                                                (billing?.subscription_level === 'free' && 'Upgrade to add add-ons')
                                            }
                                            loading={billingProductLoading === addon.type}
                                            onClick={() =>
                                                initiateProductUpgrade(
                                                    addon,
                                                    currentAndUpgradePlans?.upgradePlan,
                                                    redirectPath
                                                )
                                            }
                                        >
                                            Add
                                        </LemonButton>
                                    ))}
                            </>
                        )}
                    </div>
                    {!addon.inclusion_only && !addon.trial && isProrated && !addon.contact_support && (
                        <p className="mt-2 text-xs text-muted text-right">
                            Pay ~${prorationAmount} today (prorated) and
                            <br />
                            {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)} every month
                            thereafter.
                        </p>
                    )}
                    {!!addon.trial && !!trialExperiment && !billing?.trial && (
                        <p className="mt-2 text-xs text-muted text-right">
                            You'll have {addon.trial.length} days to try it out. Then you'll be charged{' '}
                            {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)}.
                        </p>
                    )}
                </div>
            </div>
            <div className="mt-3 ml-11">
                {addonFeatures?.length > 2 && (
                    <div>
                        <p className="ml-0 mb-2 max-w-200">Features included:</p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
                            {addonFeatures
                                .filter((feature) => !feature.entitlement_only)
                                .map((feature, index) => (
                                    <div
                                        className="flex gap-x-2 items-center mb-2"
                                        key={'addon-features-' + addon.type + index}
                                    >
                                        <IconCheckCircle className="text-success" />
                                        <Tooltip key={feature.key} title={feature.description}>
                                            <b>
                                                {feature.name}
                                                {feature.note ? ': ' + feature.note : ''}
                                            </b>
                                        </Tooltip>
                                    </div>
                                ))}
                        </div>
                    </div>
                )}
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
            <LemonModal
                isOpen={trialModalOpen}
                onClose={() => setTrialModalOpen(false)}
                title={`Start your ${addon.name} trial`}
                description={`You'll have ${addon.trial?.length} days to try it out before being charged.`}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setTrialModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" onClick={activateTrial} loading={trialLoading}>
                            Start trial
                        </LemonButton>
                    </>
                }
            >
                <p className="mb-1.5">Here's some stuff about the trial:</p>
                <ul className="space-y-0.5">
                    <li className="ml-2">
                        🎉 It's <b>free!</b>
                    </li>
                    <li className="ml-2">
                        📅 The trial is for <b>{addon.trial?.length} days</b>
                    </li>
                    <li className="ml-2">
                        🚀 You'll get access to <b>all the features</b> of the plan immediately
                    </li>
                    <li className="ml-2">
                        📧 3 days before the trial ends, you'll be emailed a reminder that you'll be charged
                    </li>
                    <li className="ml-2">
                        🚫 If you don't want to be charged, you can cancel anytime before the trial ends
                    </li>
                    <li className="ml-2">
                        💵 At the end of the trial, you'll be be subscribed and charged{' '}
                        {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)}
                    </li>
                    <li className="ml-2">
                        ☎️ If you have any questions, you can{' '}
                        <Link
                            onClick={() => {
                                setTrialModalOpen(false)
                                openSupportForm({ kind: 'support', target_area: 'billing' })
                            }}
                            className="cursor-pointer"
                        >
                            contact us
                        </Link>
                    </li>
                </ul>
            </LemonModal>
        </div>
    )
}
