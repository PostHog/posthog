import { IconCheckCircle, IconDocument, IconPlus } from '@posthog/icons'
import { LemonButton, LemonSelectOptions, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { getProductIcon } from 'scenes/products/Products'

import { BillingProductV2AddonType } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { ProductPricingModal } from './ProductPricingModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

export const BillingProductAddon = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { billing, redirectPath } = useValues(billingLogic)
    const { isPricingModalOpen, currentAndUpgradePlans, surveyID, billingProductLoading } = useValues(
        billingProductLogic({ product: addon })
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

    return (
        <div className="bg-side rounded p-6 flex flex-col">
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
                        <div>
                            <p className="ml-0 mb-0">{addon.description}</p>
                        </div>
                    </div>
                </div>
                <div className="ml-4 mr-4 mt-2 self-center flex gap-x-2 whitespace-nowrap">
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
                            <LemonButton
                                type="secondary"
                                disableClientSideRouting
                                onClick={() => {
                                    toggleIsPricingModalOpen()
                                }}
                            >
                                View pricing
                            </LemonButton>
                            {!addon.inclusion_only && (
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlus />}
                                    size="small"
                                    to={`/api/billing-v2/activation?products=${addon.type}:${
                                        currentAndUpgradePlans?.upgradePlan?.plan_key
                                    }${redirectPath && `&redirect_path=${redirectPath}`}`}
                                    disableClientSideRouting
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
