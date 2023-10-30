import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { billingProductLogic } from './billingProductLogic'
import { useActions, useValues } from 'kea'
import { BillingProductV2Type } from '~/types'
import { billingLogic } from './billingLogic'

export const UnsubscribeSurveyModal = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { surveyID, surveyResponseValue } = useValues(billingProductLogic({ product }))
    const { setSurveyResponseValue, setSurveyID, reportSurveySent } = useActions(billingProductLogic({ product }))
    const { deactivateProduct } = useActions(billingLogic)

    const textAreaNotEmpty = surveyResponseValue.length > 0
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
                    value={surveyResponseValue}
                    onChange={setSurveyResponseValue}
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
                            reportSurveySent(surveyID, surveyResponseValue)
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
