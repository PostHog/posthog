import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconPlus } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonTag } from '@posthog/lemon-ui'

import { TRIAL_CANCELLATION_SURVEY_ID, UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { BillingProductV2AddonType } from '~/types'

import { billingLogic } from './billingLogic'
import { formatFlatRate } from './BillingProductAddon'
import { billingProductLogic } from './billingProductLogic'
import { ConfirmDowngradeModal } from './ConfirmDowngradeModal'
import { ConfirmUpgradeModal } from './ConfirmUpgradeModal'
import { DATA_PIPELINES_CUTOFF_DATE } from './constants'
import { TrialCancellationSurveyModal } from './TrialCancellationSurveyModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

interface BillingProductAddonActionsProps {
    addon: BillingProductV2AddonType
    productRef?: React.RefObject<HTMLDivElement>
    buttonSize?: LemonButtonProps['size']
    ctaTextOverride?: string
    align?: 'left' | 'right'
    /** Collapse pricing into the CTA: hide the paragraph below and swap the next-to-button flat rate for the prorated amount when it applies. */
    hidePricingNote?: boolean
}

export const BillingProductAddonActions = ({
    addon,
    productRef,
    buttonSize,
    ctaTextOverride,
    align = 'right',
    hidePricingNote = false,
}: BillingProductAddonActionsProps): JSX.Element => {
    const { billing, billingError, currentPlatformAddon, unusedPlatformAddonAmount, switchPlanLoading } =
        useValues(billingLogic)
    const {
        currentAndUpgradePlans,
        billingProductLoading,
        trialLoading,
        isSubscribedToAnotherAddon,
        isDataPipelinesDeprecated,
        isLowerTierThanCurrentAddon,
        proratedAmount,
        isProrated,
        surveyID,
    } = useValues(billingProductLogic({ product: addon, productRef }))

    const { toggleIsPricingModalOpen, reportSurveyShown, setSurveyResponse, initiateProductUpgrade, activateTrial } =
        useActions(billingProductLogic({ product: addon }))
    const { showConfirmUpgradeModal, showConfirmDowngradeModal } = useActions(billingProductLogic({ product: addon }))
    const { reportBillingAddonPlanSwitchStarted } = useActions(eventUsageLogic)
    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    const isTrialEligible = !!addon.trial
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

    const renderTrialActions = (): JSX.Element | null => {
        // Hide Cancel button only for Enterprise 'standard' trials (typically sales-managed)
        if (addon.type === 'enterprise' && billing?.trial?.type !== 'autosubscribe') {
            return null
        }
        return (
            <LemonButton
                type="primary"
                size="small"
                onClick={() => {
                    setSurveyResponse('$survey_response_1', addon.type)
                    reportSurveyShown(TRIAL_CANCELLATION_SURVEY_ID, addon.type)
                }}
                loading={trialLoading}
            >
                Cancel trial
            </LemonButton>
        )
    }

    const renderPurchaseActions = (): JSX.Element => {
        const hasFlatRate = !!currentAndUpgradePlans?.upgradePlan?.flat_rate
        // Drop the flat-rate label when the caller already shows the headline price, unless proration or trial applies.
        const showLabel = hasFlatRate && !(hidePricingNote && !isTrialEligible && !isProrated)

        return (
            <>
                {hasFlatRate ? (
                    showLabel ? (
                        <h4 className="leading-5 font-bold mb-0 flex gap-x-0.5">
                            {isTrialEligible ? (
                                <span>{addon.trial?.length} day free trial</span>
                            ) : hidePricingNote && isProrated ? (
                                <span>${proratedAmount.toFixed(2)} today (prorated)</span>
                            ) : (
                                <span>{formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)}</span>
                            )}
                        </h4>
                    ) : null
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
        if (
            addon.inclusion_only ||
            addon.contact_support ||
            billing?.trial ||
            addon.subscribed ||
            addon.included_with_main_product ||
            hidePricingNote
        ) {
            return null
        }

        const pricingInfoClassName = clsx('mt-2 text-xs text-secondary', align === 'left' ? 'text-left' : 'text-right')

        if (isTrialEligible && !isSubscribedToAnotherAddon) {
            return (
                <p className={pricingInfoClassName}>
                    You'll have {addon.trial?.length} days to try it out. Then you'll be charged{' '}
                    {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)}.
                </p>
            )
        }

        if (isProrated && !isSubscribedToAnotherAddon) {
            return (
                <p className={pricingInfoClassName}>
                    Pay ~${proratedAmount.toFixed(2)} today (prorated) and
                    <br />
                    {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)} every month thereafter.
                </p>
            )
        }

        // Upgrading from another add-on to this one
        if (isSubscribedToAnotherAddon && !isLowerTierThanCurrentAddon && isProrated) {
            const amountDue = Math.max(0, proratedAmount - unusedPlatformAddonAmount)
            return (
                <p className={pricingInfoClassName}>
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

        const hasFlatRate = !!upgradePlan.flat_rate
        const amountDue = Math.max(0, proratedAmount - unusedPlatformAddonAmount)
        const showLabel = hasFlatRate && !(hidePricingNote && !isProrated)

        return (
            <>
                {showLabel && (
                    <h4 className="leading-5 font-bold mb-0 flex gap-x-0.5">
                        {hidePricingNote && isProrated ? (
                            <span>${amountDue.toFixed(2)} today (prorated)</span>
                        ) : (
                            formatFlatRate(Number(upgradePlan.unit_amount_usd), upgradePlan.unit)
                        )}
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
    } else if (!billing?.trial && isSubscribedToAnotherAddon && isLowerTierThanCurrentAddon) {
        content = renderDowngradeActions()
    } else if (!billing?.trial && isSubscribedToAnotherAddon && !isLowerTierThanCurrentAddon) {
        content = renderUpgradeActions()
    }

    return (
        <div className={clsx(align === 'right' && 'min-w-64')}>
            <div
                className={clsx(
                    'mt-2 self-center flex items-center gap-x-3 whitespace-nowrap justify-end',
                    align === 'left' ? 'flex-row-reverse' : 'ml-4'
                )}
            >
                {content}
            </div>
            {renderPricingInfo()}
            {surveyID === UNSUBSCRIBE_SURVEY_ID && <UnsubscribeSurveyModal product={addon} />}
            {surveyID === TRIAL_CANCELLATION_SURVEY_ID && <TrialCancellationSurveyModal product={addon} />}
            <ConfirmUpgradeModal product={addon} />
            <ConfirmDowngradeModal product={addon} />
        </div>
    )
}
