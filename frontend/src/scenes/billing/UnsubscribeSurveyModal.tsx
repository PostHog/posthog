import './UnsubscribeSurveyModal.scss'

import { LemonBanner, LemonButton, LemonModal, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { ExportsUnsubscribeTable, exportsUnsubscribeTableLogic } from './ExportsUnsubscribeTable'

export const UnsubscribeSurveyModal = ({
    product,
}: {
    product: BillingProductV2Type | BillingProductV2AddonType
}): JSX.Element | null => {
    const { surveyID, surveyResponse, isAddonProduct } = useValues(billingProductLogic({ product }))
    const { setSurveyResponse, reportSurveyDismissed } = useActions(billingProductLogic({ product }))
    const { deactivateProduct, resetUnsubscribeError } = useActions(billingLogic)
    const { unsubscribeError, billingLoading, billing } = useValues(billingLogic)
    const { unsubscribeDisabledReason, itemsToDisable } = useValues(exportsUnsubscribeTableLogic)

    const textAreaNotEmpty = surveyResponse['$survey_response']?.length > 0
    const includesPipelinesAddon =
        product.type == 'data_pipelines' ||
        (product.type == 'product_analytics' &&
            (product as BillingProductV2Type)?.addons?.filter((addon) => addon.type === 'data_pipelines')[0]
                ?.subscribed) ||
        billing?.subscription_level === 'paid'

    const action = isAddonProduct ? 'Remove addon' : 'Downgrade'
    const actionVerb = isAddonProduct ? 'removing addon' : 'downgrading'
    return (
        <LemonModal
            onClose={() => {
                reportSurveyDismissed(surveyID)
                resetUnsubscribeError()
            }}
            width="max(44vw)"
            title={
                billing?.subscription_level === 'paid'
                    ? `Why are you ${actionVerb}?`
                    : `Why are you ${actionVerb} from ${product.name}?`
            }
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            reportSurveyDismissed(surveyID)
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type={textAreaNotEmpty ? 'primary' : 'secondary'}
                        disabledReason={includesPipelinesAddon && unsubscribeDisabledReason}
                        onClick={() => {
                            deactivateProduct(
                                billing?.subscription_level === 'paid' && !isAddonProduct
                                    ? 'all_products'
                                    : product.type
                            )
                        }}
                        loading={billingLoading}
                    >
                        {action}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3.5">
                {unsubscribeError ? (
                    <LemonBanner type="error">
                        <p>
                            {unsubscribeError.detail} {unsubscribeError.link}
                        </p>
                    </LemonBanner>
                ) : (
                    <LemonBanner type="info">
                        <p>
                            Any outstanding invoices will be billed immediately.{' '}
                            <Link to={billing?.stripe_portal_url} target="_blank">
                                View invoices
                            </Link>
                        </p>
                    </LemonBanner>
                )}
                <LemonTextArea
                    data-attr="unsubscribe-reason-survey-textarea"
                    placeholder={`Reason for ${actionVerb}...`}
                    value={surveyResponse['$survey_response']}
                    onChange={(value) => {
                        setSurveyResponse(value, '$survey_response')
                    }}
                />
                <LemonBanner type="info">
                    <p>
                        {'Need to control your costs? Learn about ways to '}
                        <Link
                            to="https://posthog.com/docs/billing/estimating-usage-costs#how-to-reduce-your-posthog-costs"
                            target="_blank"
                            onClick={() => {
                                reportSurveyDismissed(surveyID)
                            }}
                        >
                            reduce your bill
                        </Link>
                        {`${product.type !== 'session_replay' ? ' or ' : ', '}`}
                        <Link
                            to="mailto:sales@posthog.com?subject=Help%20reducing%20PostHog%20bill"
                            target="_blank"
                            onClick={() => {
                                reportSurveyDismissed(surveyID)
                            }}
                        >
                            chat with support
                        </Link>
                        {product.type === 'session_replay' && (
                            <>
                                {', or '}
                                <Link
                                    to="mailto:sales@posthog.com?subject=Joining%session%replay%controls%20beta"
                                    target="_blank"
                                    onClick={() => {
                                        reportSurveyDismissed(surveyID)
                                    }}
                                >
                                    join our beta
                                </Link>
                                {' for tuning recording volume with sampling and minimum duration.'}
                            </>
                        )}
                        .
                    </p>
                </LemonBanner>
            </div>
            {includesPipelinesAddon && itemsToDisable.length > 0 ? (
                <div className="mt-6">
                    <h3 className="mt-2 mb-2 mr-8">Important: Disable remaining export apps</h3>
                    <p>
                        To avoid unexpected impact on your data, you must explicitly disable the following apps and
                        exports before unsubscribing:
                    </p>
                    <ExportsUnsubscribeTable />
                </div>
            ) : null}
        </LemonModal>
    )
}
