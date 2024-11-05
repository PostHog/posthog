import { IconCheckCircle, IconPlus } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { toSentenceCase } from 'lib/utils'

import { BillingProductV2AddonType } from '~/types'

import { formatFlatRate } from './BillingProductAddon'

interface BillingProductAddonActionsProps {
    addon: BillingProductV2AddonType
    billing: any // Replace with proper type
    billingProductLoading: string | null
    billingError: any // Replace with proper type
    upgradePlan: any // Replace with proper type
    currentAndUpgradePlans: any // Replace with proper type
    trialExperiment: string
    trialLoading: boolean
    isProrated: boolean
    prorationAmount: string
    // Actions
    setSurveyResponse: (key: string, value: string) => void
    reportSurveyShown: (surveyId: string, type: string) => void
    toggleIsPricingModalOpen: () => void
    handleTrialActivation: () => void
    initiateProductUpgrade: (addon: BillingProductV2AddonType, plan: any, redirectPath: string) => void
    cancelTrial: () => void
}

export const BillingProductAddonActions = ({
    addon,
    billing,
    billingProductLoading,
    billingError,
    upgradePlan,
    currentAndUpgradePlans,
    trialExperiment,
    trialLoading,
    isProrated,
    prorationAmount,
    // Actions
    setSurveyResponse,
    reportSurveyShown,
    toggleIsPricingModalOpen,
    handleTrialActivation,
    initiateProductUpgrade,
    cancelTrial,
}: BillingProductAddonActionsProps): JSX.Element => {
    const renderSubscribedActions = (): JSX.Element | null => {
        if (addon.contact_support) {
            return null
        }
        return (
            <More
                overlay={
                    <LemonButton
                        fullWidth
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
                        You are currently on a free trial for <b>{toSentenceCase(billing.trial.target)}</b> until{' '}
                        <b>{dayjs(billing.trial.expires_at).format('LL')}</b>. At the end of the trial{' '}
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
            {addon.type !== 'enterprise' && (
                <LemonButton type="primary" size="small" onClick={cancelTrial} loading={trialLoading} className="mt-1">
                    Cancel trial
                </LemonButton>
            )}
        </div>
    )

    const renderPurchaseActions = (): JSX.Element => {
        const showPricing = currentAndUpgradePlans?.upgradePlan?.flat_rate
        const isTrialEligible = addon.trial && !!trialExperiment

        return (
            <>
                {showPricing ? (
                    <h4 className="leading-5 font-bold mb-0 space-x-0.5">
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

                {!addon.inclusion_only && (
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
                        onClick={
                            isTrialEligible
                                ? handleTrialActivation
                                : () => initiateProductUpgrade(addon, currentAndUpgradePlans?.upgradePlan, '')
                        }
                    >
                        {isTrialEligible ? 'Start trial' : 'Add'}
                    </LemonButton>
                )}
            </>
        )
    }

    const renderPricingInfo = (): JSX.Element | null => {
        if (addon.inclusion_only || addon.contact_support || billing?.trial || addon.subscribed) {
            return null
        }

        if (addon.trial && trialExperiment) {
            return (
                <p className="mt-2 text-xs text-muted text-right">
                    You'll have {addon.trial.length} days to try it out. Then you'll be charged{' '}
                    {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)}.
                </p>
            )
        }

        if (isProrated) {
            return (
                <p className="mt-2 text-xs text-muted text-right">
                    Pay ~${prorationAmount} today (prorated) and
                    <br />
                    {formatFlatRate(Number(upgradePlan?.unit_amount_usd), upgradePlan?.unit)} every month thereafter.
                </p>
            )
        }

        return null
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
    } else if (billing?.trial?.target === addon.type) {
        // Current trial on this addon
        content = renderTrialActions()
    } else if (addon.contact_support) {
        content = (
            <LemonButton type="secondary" to="https://posthog.com/talk-to-a-human">
                Contact support
            </LemonButton>
        )
    } else if (!billing?.trial) {
        // Customer is not subscribed to any trial
        // TODO: add support for when subscription to paid here
        content = renderPurchaseActions()
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
