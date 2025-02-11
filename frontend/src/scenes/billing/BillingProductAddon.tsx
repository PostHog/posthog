import { IconCheckCircle, IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelectOptions, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { capitalizeFirstLetter, humanFriendlyCurrency } from 'lib/utils'
import { ReactNode, useRef } from 'react'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType } from '~/types'

import { BillingGauge } from './BillingGauge'
import { billingLogic } from './billingLogic'
import { BillingProductAddonActions } from './BillingProductAddonActions'
import { billingProductAddonLogic } from './billingProductAddonLogic'
import { billingProductLogic } from './billingProductLogic'
import { BillingProductPricingTable } from './BillingProductPricingTable'
import { ProductPricingModal } from './ProductPricingModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

export const formatFlatRate = (flatRate: number, unit: string | null): string | ReactNode => {
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
    const { billing } = useValues(billingLogic)
    const { isPricingModalOpen, currentAndUpgradePlans, surveyID, trialModalOpen, trialLoading, showTierBreakdown } =
        useValues(billingProductLogic({ product: addon, productRef }))
    const { toggleIsPricingModalOpen, setTrialModalOpen, activateTrial, setShowTierBreakdown } = useActions(
        billingProductLogic({ product: addon })
    )
    const { openSupportForm } = useActions(supportLogic)
    const logic = billingProductAddonLogic({ addon })
    const { gaugeItems } = useValues(logic)

    const upgradePlan = currentAndUpgradePlans?.upgradePlan

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

    return (
        <div
            className="bg-surface-secondary rounded p-6 flex flex-col"
            ref={productRef}
            data-attr={`billing-product-addon-${addon.type}`}
        >
            <div className="sm:flex justify-between gap-x-4">
                {/* Header */}
                <div className="flex gap-x-4">
                    <div className="w-8">{getProductIcon(addon.name, addon.icon_key, 'text-2xl')}</div>
                    <div>
                        <div className="flex gap-x-2 items-center mt-0 mb-2 ">
                            <h4 className="leading-5 mb-1 font-bold">{addon.name}</h4>
                            {addon.inclusion_only ? (
                                <div className="flex gap-x-2">
                                    <Tooltip
                                        title={`Automatically included with your plan.${
                                            addon.type === 'enhanced_persons'
                                                ? ' Used based on whether you capture person profiles with your events.'
                                                : ''
                                        }`}
                                    >
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

                {/* Actions */}
                <BillingProductAddonActions productRef={productRef} addon={addon} />
            </div>

            {/* Features */}
            <div className={clsx('mt-3', { 'ml-11': addon.type !== 'mobile_replay' })}>
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

                {addon.type === 'mobile_replay' && addon.subscribed && (
                    <>
                        <div className="flex w-full items-center gap-x-8">
                            <LemonButton
                                icon={showTierBreakdown ? <IconChevronDown /> : <IconChevronRight />}
                                onClick={() => setShowTierBreakdown(!showTierBreakdown)}
                            />
                            <div className="grow">
                                <BillingGauge items={gaugeItems} product={addon} />
                            </div>
                            <div className="flex justify-end gap-8 flex-wrap items-end shrink-0">
                                <Tooltip
                                    title={`The current amount you have been billed for mobile recordings this ${billing?.billing_period?.interval}.`}
                                >
                                    <div className="flex flex-col items-center">
                                        <div className="font-bold text-3xl leading-7">
                                            {humanFriendlyCurrency(
                                                parseFloat(addon.current_amount_usd || '0') *
                                                    (1 -
                                                        (billing?.discount_percent
                                                            ? billing.discount_percent / 100
                                                            : 0))
                                            )}
                                        </div>
                                        <span className="text-xs text-muted">
                                            {capitalizeFirstLetter(billing?.billing_period?.interval || '')}
                                            -to-date
                                        </span>
                                    </div>
                                </Tooltip>
                            </div>
                        </div>

                        {showTierBreakdown && <BillingProductPricingTable product={addon} />}
                    </>
                )}
            </div>

            {/* Pricing modal */}
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

            {/* Unsubscribe survey modal */}
            {surveyID && <UnsubscribeSurveyModal product={addon} />}

            {/* Trial modal */}
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
