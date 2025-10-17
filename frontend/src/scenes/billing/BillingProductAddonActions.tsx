import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconPlus } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS, TRIAL_CANCELLATION_SURVEY_ID, UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { toSentenceCase } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { BillingProductV2AddonType } from '~/types'

import { formatFlatRate } from './BillingProductAddon'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { DATA_PIPELINES_CUTOFF_DATE } from './constants'

interface BillingProductAddonActionsProps {
    addon: BillingProductV2AddonType
    productRef?: React.RefObject<HTMLDivElement>
    buttonSize?: LemonButtonProps['size']
    ctaTextOverride?: string
}

export const BillingProductAddonActions = ({
    addon,
    productRef,
    buttonSize,
    ctaTextOverride,
}: BillingProductAddonActionsProps): JSX.Element => {
    const { billing, billingError, currentPlatformAddon, unusedPlatformAddonAmount, switchPlanLoading } =
        useValues(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        currentAndUpgradePlans,
        billingProductLoading,
        trialLoading,
        isSubscribedToAnotherAddon,
        isDataPipelinesDeprecated,
        isLowerTierThanCurrentAddon,
        proratedAmount,
        isProrated,
    } = useValues(billingProductLogic({ product: addon, productRef }))

    const { toggleIsPricingModalOpen, reportSurveyShown, setSurveyResponse, initiateProductUpgrade, activateTrial } =
        useActions(billingProductLogic({ product: addon }))
    const { showConfirmUpgradeModal, showConfirmDowngradeModal } = useActions(billingProductLogic({ product: addon }))
    const { reportBillingAddonPlanSwitchStarted } = useActions(eventUsageLogic)
    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    const isTrialEligible = !!addon.trial
    const isSwitchPlanEnabled = !!featureFlags[FEATURE_FLAGS.SWITCH_SUBSCRIPTION_PLAN]

    const renderSubscribedActions = (): JSX.Element | null => {
        if (addon.contact_support) {
            return null
        }
        return (
            <More
                overlay={
                    <LemonButton
                        fullWidth
                        disabledReason={
                            (switchPlanLoading ? 'Switching plans...' : undefined) ||
                            (isDataPipelinesDeprecated
                                ? `Data pipelines have moved to new, usage-based pricing with generous free allowance, and old ingestion-based pricing ended on ${DATA_PIPELINES_CUTOFF_DATE}.`
                                : undefined)
                        }
                        onClick={() => {
                            setSurveyResponse('$survey_response_1', addon.type)
                            reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, addon.type)
                        }}
                    >
                        Remove add-on
                    </LemonButton>
                }
            />
        )
    }

    const renderTrialActions = (): JSX.Element => (
        <div className="flex flex-col items-end justify-end">
            <Tooltip
                title={
                    <p>
                        You are currently on a free trial for <b>{toSentenceCase(billing?.trial?.target || '')}</b>{' '}
                        until <b>{dayjs(billing?.trial?.expires_at).format('LL')}</b>. At the end of the trial{' '}
                        {billing?.trial?.type === 'autosubscribe'
                            ? 'you will be automatically subscribed to the plan.'
                            : 'you will be asked to subscribe. If you choose not to, you will lose access to the features.'}
                    </p>
                }
            >
                <LemonTag type="completion" icon={<IconCheckCircle />}>
                    You're on a trial for this add-on
                </LemonTag>
            </Tooltip>
            {addon.type !== 'enterprise' && (
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => {
                        setSurveyResponse('$survey_response_1', addon.type)
                        reportSurveyShown(TRIAL_CANCELLATION_SURVEY_ID, addon.type)
                    }}
                    loading={trialLoading}
                    className="mt-1"
                >
                    Cancel trial
                </LemonButton>
            )}
        </div>
    )

    const renderPurchaseActions = (): JSX.Element => {
        const showPricing = currentAndUpgradePlans?.upgradePlan?.flat_rate

        return (
            <>
                {showPricing ? (
                    <h4 className="leading-5 font-bold mb-0 flex gap-x-0.5">
                        {isTrialEligible ? (
                            <span>{addon.trial?.length} day free trial</span>
                        ) : (
                            <span>{formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)}</span>
                        )}
                    </h4>
                ) : (
                    <LemonButton type="secondary" onClick={toggleIsPricingModalOpen}>
                        View pricing
                    </LemonButton>
                )}

                {!addon.inclusion_only && !isDataPipelinesDeprecated && (
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        size={buttonSize || 'small'}
                        disableClientSideRouting
                        disabledReason={
                            (billingError && billingError.message) ||
                            (billing?.subscription_level === 'free' && 'Upgrade to add add-ons')
                        }
                        loading={billingProductLoading === addon.type || trialLoading}
                        onClick={
                            isTrialEligible
                                ? () => activateTrial()
                                : () => initiateProductUpgrade(addon, currentAndUpgradePlans?.upgradePlan, '')
                        }
                    >
                        {ctaTextOverride ?? (isTrialEligible ? 'Start trial' : 'Add')}
                    </LemonButton>
                )}
            </>
        )
    }

    const renderPricingInfo = (): JSX.Element | null => {
        // Don't render if
        // - the product is inclusion only (it's automatically included and can't be subscribed to)
        // - the plan requires contacting support
        // - the customer is on a trial
        // - the customer is already subscribed to the product
        // - the product is included with the main product
        if (
            addon.inclusion_only ||
            addon.contact_support ||
            billing?.trial ||
            addon.subscribed ||
            addon.included_with_main_product
        ) {
            return null
        }

        if (isTrialEligible && !isSubscribedToAnotherAddon) {
            return (
                <p className="mt-2 text-xs text-secondary text-right">
                    You'll have {addon.trial?.length} days to try it out. Then you'll be charged{' '}
                    {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)}.
                </p>
            )
        }

        if (isProrated && !isSubscribedToAnotherAddon) {
            return (
                <p className="mt-2 text-xs text-secondary text-right">
                    Pay ~${proratedAmount.toFixed(2)} today (prorated) and
                    <br />
                    {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)} every month thereafter.
                </p>
            )
        }

        // Upgrading from another add-on to this one
        if (isSwitchPlanEnabled && isSubscribedToAnotherAddon && !isLowerTierThanCurrentAddon && isProrated) {
            const amountDue = Math.max(0, proratedAmount - unusedPlatformAddonAmount)
            return (
                <p className="mt-2 text-xs text-secondary text-right">
                    Pay ~${amountDue.toFixed(2)} today (prorated) and
                    <br />
                    {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)} every month thereafter.
                </p>
            )
        }

        return null
    }

    const renderDowngradeActions = (): JSX.Element | null => {
        if (!upgradePlan || !currentPlatformAddon) {
            return null
        }

        return (
            <More
                overlay={
                    <LemonButton
                        fullWidth
                        disabledReason={switchPlanLoading ? 'Switching plans...' : undefined}
                        onClick={() => {
                            reportBillingAddonPlanSwitchStarted(currentPlatformAddon.type, addon.type, 'downgrade')
                            showConfirmDowngradeModal()
                        }}
                    >
                        Downgrade
                    </LemonButton>
                }
            />
        )
    }

    const renderUpgradeActions = (): JSX.Element | null => {
        if (!upgradePlan || !currentPlatformAddon) {
            return null
        }

        const showPricing = upgradePlan.flat_rate

        return (
            <>
                {showPricing && (
                    <h4 className="leading-5 font-bold mb-0 flex gap-x-0.5">
                        {formatFlatRate(Number(upgradePlan.unit_amount_usd), upgradePlan.unit)}
                    </h4>
                )}

                <LemonButton
                    type="primary"
                    disabledReason={switchPlanLoading ? 'Switching plans...' : undefined}
                    onClick={() => {
                        reportBillingAddonPlanSwitchStarted(currentPlatformAddon.type, addon.type, 'upgrade')
                        showConfirmUpgradeModal()
                    }}
                >
                    Upgrade
                </LemonButton>
            </>
        )
    }

    let content
    if (addon.subscribed && !addon.inclusion_only) {
        content = renderSubscribedActions()
    } else if (addon.included_with_main_product) {
        content = (
            <LemonTag type="completion" icon={<IconCheckCircle />}>
                Included with plan
            </LemonTag>
        )
    } else if (billing?.trial && billing?.trial?.target === addon.type) {
        // Current trial on this addon
        content = renderTrialActions()
    } else if (addon.contact_support) {
        content = (
            <LemonButton type="secondary" to="https://posthog.com/talk-to-a-human">
                Contact support
            </LemonButton>
        )
    } else if (!billing?.trial && !isSubscribedToAnotherAddon) {
        // Customer is not subscribed to any trial
        // We don't allow multiple add-ons to be subscribed to at the same time so this checks if the customer is subscribed to another add-on
        // TODO: add support for when a customer has a Paid Plan trial
        content = renderPurchaseActions()
    } else if (!billing?.trial && isSubscribedToAnotherAddon && isLowerTierThanCurrentAddon && isSwitchPlanEnabled) {
        content = renderDowngradeActions()
    } else if (!billing?.trial && isSubscribedToAnotherAddon && !isLowerTierThanCurrentAddon && isSwitchPlanEnabled) {
        content = renderUpgradeActions()
    }

    return (
        <div className="min-w-64">
            <div className="ml-4 mt-2 self-center flex items-center justify-end gap-x-3 whitespace-nowrap">
                {content}
            </div>
            {renderPricingInfo()}
        </div>
    )
}
