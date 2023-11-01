import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { billingProductLogic } from './billingProductLogic'
import { useActions, useValues } from 'kea'
import { BillingProductV2Type } from '~/types'
import { billingLogic } from './billingLogic'

export const UnsubscribeSurveyModal = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { surveyID, surveyResponse } = useValues(billingProductLogic({ product }))
    const { setSurveyResponse, setSurveyID, reportSurveySent } = useActions(billingProductLogic({ product }))
    const { deactivateProduct } = useActions(billingLogic)

    const textAreaNotEmpty = surveyResponse['$survey_repsonse']?.length > 0
    return (
        <LemonModal
            onClose={() => {
                setSurveyID('')
            }}
            title="Let us know why you're unsubscribing"
        >
            <div className="flex flex-col">
                <LemonTextArea
                    placeholder={'Start typing...'}
                    value={surveyResponse['$survey_response']}
                    onChange={(value) => {
                        setSurveyResponse(value, '$survey_response')
                    }}
                />
                <div className="flex justify-between pt-2 gap-8">
                    <LemonButton
                        type={'tertiary'}
                        status={'muted'}
                        to="mailto:sales@posthog.com?subject=Issues%20With%20Bill"
                    >
                        Big bills got you down? Chat with support
                    </LemonButton>
                    <LemonButton
                        type={textAreaNotEmpty ? 'primary' : 'tertiary'}
                        status={textAreaNotEmpty ? 'primary' : 'muted'}
                        onClick={() => {
                            reportSurveySent(surveyID, surveyResponse)
                            deactivateProduct(product.type)
                        }}
                    >
                        Unsubscribe
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}
