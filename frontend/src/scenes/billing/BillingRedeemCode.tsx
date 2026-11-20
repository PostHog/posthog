import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { couponLogic } from 'scenes/coupons/couponLogic'

export function BillingRedeemCode(): JSX.Element {
    const { isCouponSubmitting } = useValues(couponLogic({}))

    return (
        <Form logic={couponLogic} props={{}} formKey="coupon" enableFormOnSubmit className="mt-6 max-w-120 space-y-2">
            <div className="flex flex-wrap items-end gap-2">
                <LemonField name="code" label="Have a coupon code?" className="flex-1 min-w-60">
                    <LemonInput placeholder="Enter your code" data-attr="billing-redeem-code-input" />
                </LemonField>
                <LemonButton
                    type="secondary"
                    htmlType="submit"
                    loading={isCouponSubmitting}
                    disabledReason={isCouponSubmitting ? 'Redeeming the code' : undefined}
                    data-attr="billing-redeem-code"
                >
                    Redeem
                </LemonButton>
            </div>
            <LemonField name="_form">
                <span />
            </LemonField>
        </Form>
    )
}
