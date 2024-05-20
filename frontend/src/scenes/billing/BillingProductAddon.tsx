import { IconCheckCircle, IconDocument, IconPlus } from '@posthog/icons'
import { LemonButton, LemonSelectOptions, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { useRef } from 'react'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { ProductPricingModal } from './ProductPricingModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

export const BillingProductAddon = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const productRef = useRef<HTMLDivElement | null>(null)
    const { billing, redirectPath, billingError } = useValues(billingLogic)
    const { isPricingModalOpen, currentAndUpgradePlans, surveyID, billingProductLoading } = useValues(
        billingProductLogic({ product: addon, productRef })
    )
    const { toggleIsPricingModalOpen, reportSurveyShown, setSurveyResponse, setBillingProductLoading } = useActions(
        billingProductLogic({ product: addon })
    )

    const productType = { plural: `${addon.unit}s`, singular: addon.unit }
    const tierDisplayOptions: LemonSelectOptions<string> = [
        { label: `Per ${productType.singular}`, value: 'individual' },
    ]

    if (billing?.has_active_subscription) {
        tierDisplayOptions.push({ label: `Current bill`, value: 'total' })
    }

    // Filter out the addon itself from the features list
    const addonFeatures = addon.features?.filter((feature) => feature.name !== addon.name)

    const is_enhanced_persons_og_customer =
        addon.type === 'enhanced_persons' &&
        addon.plans?.find((plan) => plan.plan_key === 'addon-20240404-og-customers')

    return (
        <div className="bg-side rounded p-6 flex flex-col" ref={productRef}>
            <div className="flex justify-between gap-x-4">
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
                        <p className="ml-0 mb-0">{addon.description}</p>
                        {is_enhanced_persons_og_customer && (
                            <p className="mt-2 mb-0">
                                <Link
                                    to="https://posthog.com/changelog/2024#person-profiles-addon"
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
                <div className="ml-4 mr-4 mt-2 self-center flex items-center gap-x-3 whitespace-nowrap">
                    {addon.docs_url && (
                        <LemonButton icon={<IconDocument />} size="small" to={addon.docs_url} tooltip="Read the docs" />
                    )}
                    {addon.subscribed && !addon.inclusion_only ? (
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
                        <LemonTag type="completion" icon={<IconCheckCircle />}>
                            Included with plan
                        </LemonTag>
                    ) : (
                        <>
                            {currentAndUpgradePlans?.upgradePlan?.flat_rate ? (
                                <h4 className="leading-5 font-bold mb-0 space-x-0.5">
                                    <span>${Number(currentAndUpgradePlans?.upgradePlan?.unit_amount_usd)}</span>
                                    <span>/</span>
                                    <span>{currentAndUpgradePlans?.upgradePlan?.unit}</span>
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
                            {!addon.inclusion_only && (
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlus />}
                                    size="small"
                                    to={`/api/billing-v2/activation?products=${addon.type}:${
                                        currentAndUpgradePlans?.upgradePlan?.plan_key
                                    }${redirectPath && `&redirect_path=${redirectPath}`}`}
                                    disableClientSideRouting
                                    disabledReason={billingError && billingError.message}
                                    loading={billingProductLoading === addon.type}
                                    onClick={() => {
                                        setBillingProductLoading(addon.type)
                                    }}
                                >
                                    Add
                                </LemonButton>
                            )}
                        </>
                    )}
                </div>
            </div>
            <div className="mt-3 ml-11">
                {addonFeatures?.length > 1 && (
                    <div>
                        <p className="ml-0 mb-2 max-w-200">Features included:</p>
                        {addonFeatures?.map((feature, i) => {
                            return (
                                i < 6 && (
                                    <div
                                        className="flex gap-x-2 items-center mb-2"
                                        key={'addon-features-' + addon.type + i}
                                    >
                                        <IconCheckCircle className="text-success" />
                                        <Tooltip key={feature.key} title={feature.description}>
                                            <b>{feature.name} </b>
                                        </Tooltip>
                                    </div>
                                )
                            )
                        })}
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
        </div>
    )
}
