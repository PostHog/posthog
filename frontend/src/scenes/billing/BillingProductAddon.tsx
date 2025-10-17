import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode, useRef } from 'react'

import { IconCheckCircle, IconInfo } from '@posthog/icons'
import { LemonSelectOptions, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TRIAL_CANCELLATION_SURVEY_ID, UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { humanFriendlyCurrency } from 'lib/utils'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType } from '~/types'

import { BillingAddonFeaturesList } from './BillingAddonFeaturesList'
import { BillingProductAddonActions } from './BillingProductAddonActions'
import { ConfirmDowngradeModal } from './ConfirmDowngradeModal'
import { ConfirmUpgradeModal } from './ConfirmUpgradeModal'
import { ProductPricingModal } from './ProductPricingModal'
import { TrialCancellationSurveyModal } from './TrialCancellationSurveyModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'
import { isProductVariantSecondary } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { DATA_PIPELINES_CUTOFF_DATE } from './constants'

export const formatFlatRate = (flatRate: number, unit: string | null): string | ReactNode => {
    if (!unit) {
        return `$${flatRate}`
    }
    return (
        <span className="inline-flex gap-x-0.5">
            <span>{humanFriendlyCurrency(flatRate)}</span>
            <span>/</span>
            <span>{unit}</span>
        </span>
    )
}

export const BillingProductAddon = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const productRef = useRef<HTMLDivElement | null>(null)
    const { billing } = useValues(billingLogic)
    const { isPricingModalOpen, currentAndUpgradePlans, surveyID, isDataPipelinesDeprecated } = useValues(
        billingProductLogic({ product: addon, productRef })
    )
    const { toggleIsPricingModalOpen } = useActions(billingProductLogic({ product: addon }))

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
                    <div>{getProductIcon(addon.name, addon.icon_key, 'text-2xl shrink-0')}</div>
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
                            {addon.legacy_product && (
                                <div>
                                    <LemonTag type="highlight" icon={<IconInfo />}>
                                        Legacy add-on
                                    </LemonTag>
                                </div>
                            )}
                            {isDataPipelinesDeprecated && (
                                <div>
                                    <Tooltip
                                        title={`Data pipelines have moved to new, usage-based pricing with a large free allowance. You can no longer upgrade to this add-on and old ingestion-based pricing ended on ${DATA_PIPELINES_CUTOFF_DATE}.`}
                                    >
                                        <LemonTag type="warning" icon={<IconInfo />}>
                                            Deprecated
                                        </LemonTag>
                                    </Tooltip>
                                </div>
                            )}
                        </div>
                        <p className="ml-0 mb-0">{addon.description} </p>
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
            <div className={clsx('mt-3', { 'ml-11': !isProductVariantSecondary(addon.type) })}>
                <BillingAddonFeaturesList
                    addonFeatures={addonFeatures?.filter((feature) => !feature.entitlement_only) || []}
                    addonType={addon.type}
                />
                <p className="ml-0 mb-0 mt-2">
                    {addon.docs_url && (
                        <>
                            <Link to={addon.docs_url}>Read the docs</Link> for more information.
                        </>
                    )}
                </p>
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
            {surveyID === UNSUBSCRIBE_SURVEY_ID && <UnsubscribeSurveyModal product={addon} />}
            {/* Trial cancellation survey modal */}
            {surveyID === TRIAL_CANCELLATION_SURVEY_ID && <TrialCancellationSurveyModal product={addon} />}
            {/* Confirm platform addon subscription upgrade */}
            <ConfirmUpgradeModal product={addon} />
            {/* Confirm platform addon subscription downgrade */}
            <ConfirmDowngradeModal product={addon} />
        </div>
    )
}
