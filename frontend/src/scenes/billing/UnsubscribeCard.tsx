import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'

import { BillingProductV2Type } from '~/types'

import { billingProductLogic } from './billingProductLogic'

export const UnsubscribeCard = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { reportSurveyShown, setSurveyResponse } = useActions(billingProductLogic({ product }))

    return (
        <div className="bg-bg-light p-4 border rounded my-4">
            <p>You're currently subscribed to the paid plan</p>
            <LemonButton
                status="danger"
                type="primary"
                onClick={() => {
                    setSurveyResponse(product.type, '$survey_response_1')
                    reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, product.type)
                }}
            >
                Downgrade to free plan
            </LemonButton>
        </div>
    )
}
