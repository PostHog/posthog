import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck, IconReceipt } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { billingLogic } from 'scenes/billing/billingLogic'

import { couponLogic } from './couponLogic'

/**
 * Compact "redeem a coupon code" entry point for the billing overview page.
 * The billing page previously only listed already-claimed coupons, so users
 * holding a valid code had no visible way to redeem it without knowing the
 * campaign-keyed `/coupons/:campaign` URL.
 */
export function CouponRedeemEntry(): JSX.Element | null {
    const { billing, billingLoading } = useValues(billingLogic)
    const { claimed, claimedDetails, isCouponSubmitting, isAdminOrOwner } = useValues(couponLogic({}))

    // Only admins/owners can claim coupons (enforced server-side); hide for everyone else.
    if (isAdminOrOwner === false) {
        return null
    }

    if (claimed) {
        return (
            <div className="mt-6 max-w-300 flex items-center gap-2 text-success">
                <IconCheck className="shrink-0" />
                <span>
                    Coupon redeemed successfully! Your benefits are now active
                    {claimedDetails?.expires_at && ` until ${dayjs(claimedDetails.expires_at).format('LL')}`}.
                </span>
            </div>
        )
    }

    // Coupons require a paid subscription. Surface this as a gate on the button rather than a
    // submit-time error so the precondition is clear before the user tries to redeem.
    const needsBilling = !billingLoading && !billing?.has_active_subscription

    return (
        <div className="mt-6 max-w-300">
            <div className="flex items-center gap-2 mb-2">
                <IconReceipt className="text-muted shrink-0" />
                <h3 className="m-0 text-base">Have a coupon code?</h3>
            </div>
            <Form
                logic={couponLogic}
                formKey="coupon"
                enableFormOnSubmit
                className="flex items-start gap-2 flex-wrap"
                props={{}}
            >
                <LemonField name="code" className="min-w-60">
                    <LemonInput placeholder="XXX-XXXXXXXXXXX" />
                </LemonField>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={isCouponSubmitting}
                    disabledReason={
                        needsBilling
                            ? 'Add a paid plan first. Coupons can only be redeemed on a paid subscription'
                            : isCouponSubmitting
                              ? 'Redeeming coupon...'
                              : undefined
                    }
                >
                    Redeem coupon
                </LemonButton>
            </Form>
        </div>
    )
}
