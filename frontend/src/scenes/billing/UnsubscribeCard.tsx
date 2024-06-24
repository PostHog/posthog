import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'

import { BillingProductV2Type } from '~/types'

import { billingProductLogic } from './billingProductLogic'

export const UnsubscribeCard = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { reportSurveyShown, setSurveyResponse } = useActions(billingProductLogic({ product }))

    return (
        <div className="p-5 gap-4 flex">
            <div className="">
                <h3>Need to take a break?</h3>
                <p className="mb-2">
                    Downgrade to the free plan at any time. You'll lose access to platform features and usage limits
                    will apply immediately.
                </p>
                <p className="">
                    Need to control your costs? Learn about ways to{' '}
                    <Link
                        to="https://posthog.com/docs/billing/estimating-usage-costs#how-to-reduce-your-posthog-costs?utm_source=app-unsubscribe"
                        target="_blank"
                    >
                        reduce your bill
                    </Link>{' '}
                    or{' '}
                    <Link to="mailto:sales@posthog.com?subject=Help%20reducing%20PostHog%20bill" target="_blank">
                        chat with support.
                    </Link>{' '}
                    Check out more about our pricing on our{' '}
                    <Link to="https://posthog.com/pricing" target="_blank">
                        pricing page
                    </Link>
                    .
                </p>
                <LemonButton
                    status="danger"
                    type="secondary"
                    size="small"
                    onClick={() => {
                        setSurveyResponse(product.type, '$survey_response_1')
                        reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, product.type)
                    }}
                >
                    Downgrade to free plan
                </LemonButton>
            </div>
        </div>
    )
}
