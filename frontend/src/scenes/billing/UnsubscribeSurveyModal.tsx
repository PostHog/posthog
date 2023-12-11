import { LemonBanner, LemonButton, LemonModal, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

export const UnsubscribeSurveyModal = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { surveyID, surveyResponse } = useValues(billingProductLogic({ product }))
    const { setSurveyResponse, reportSurveySent, reportSurveyDismissed } = useActions(billingProductLogic({ product }))
    const { deactivateProduct } = useActions(billingLogic)

    const textAreaNotEmpty = surveyResponse['$survey_response']?.length > 0
    return (
        <LemonModal
            onClose={() => {
                reportSurveyDismissed(surveyID)
            }}
            width={'max(40vw)'}
        >
            <div>
                <h3 className="mt-2 mb-4">{`Why are you unsubscribing from ${product.name}?`}</h3>
                <div className="flex flex-col gap-3.5">
                    <LemonTextArea
                        data-attr="unsubscribe-reason-survey-textarea"
                        placeholder={'Start typing...'}
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
                        </p>
                    </LemonBanner>
                    <div className="flex justify-end gap-4">
                        <LemonButton
                            type="tertiary"
                            status="muted"
                            onClick={() => {
                                reportSurveyDismissed(surveyID)
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type={textAreaNotEmpty ? 'primary' : 'tertiary'}
                            status={textAreaNotEmpty ? 'primary' : 'muted'}
                            onClick={() => {
                                textAreaNotEmpty
                                    ? reportSurveySent(surveyID, surveyResponse)
                                    : reportSurveyDismissed(surveyID)
                                deactivateProduct(product.type)
                            }}
                        >
                            Unsubscribe
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
