import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { WavingHog } from 'lib/components/hedgehogs'
import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'

import { BillingProductV2Type } from '~/types'

import { billingProductLogic } from './billingProductLogic'

export const UnsubscribeCard = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { reportSurveyShown, setSurveyResponse } = useActions(billingProductLogic({ product }))

    return (
        <div className="bg-bg-light p-5 border gap-4 rounded flex justify-start w-1/2">
            <div className="">
                <h3>You're subscribed to the paid plan</h3>
                <p>
                    You can downgrade to the free plan at any time. You will lose access to some features. Checkout more
                    about our pricing on our{' '}
                    <Link to="https://posthog.com/pricing" target="_blank">
                        pricing page
                    </Link>
                    .
                </p>
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
            <div className="flex justify-center items-center w-full">
                <WavingHog className="h-32 w-32" />
            </div>
        </div>
    )
}
