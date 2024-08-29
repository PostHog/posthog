import { LemonButton, LemonCheckbox, LemonDivider, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { billingLogic } from './billingLogic'

export const AnnualCreditModal = (): JSX.Element | null => {
    const { showAnnualCreditModal, submitSelfServeCreditForm } = useActions(billingLogic)
    const { selfServeCreditEligibility, isSelfServeCreditFormSubmitting, selfServeCreditForm } = useValues(billingLogic)

    // TODO(@zach): move into a function in the logic
    const getDiscount = (): number => {
        const monthlySpend = +selfServeCreditForm.creditInput
        if (monthlySpend < 6000) {
            return 0
        }
        if (monthlySpend < 20000) {
            return 0.1
        }
        if (monthlySpend < 60000) {
            return 0.2
        }
        if (monthlySpend < 100000) {
            return 0.25
        }
        return 0.3
    }

    return (
        <LemonModal
            onClose={() => showAnnualCreditModal(false)}
            width="max(44vw)"
            title="Wow, big spender!"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => showAnnualCreditModal(false)}
                        disabled={isSelfServeCreditFormSubmitting}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => submitSelfServeCreditForm()}
                        loading={isSelfServeCreditFormSubmitting}
                    >
                        Purchase{' '}
                        {selfServeCreditForm.creditInput ? `$${selfServeCreditForm.creditInput.toLocaleString()}` : ''}{' '}
                        credits
                    </LemonButton>
                </>
            }
        >
            <Form formKey="selfServeCreditForm" logic={billingLogic} enableFormOnSubmit>
                <div className="flex flex-col gap-3.5">
                    <p className="mb-0">
                        You're using PostHog more and you're now eligible to purchase credits upfront for a discount.
                        This can help make your spending more predictable. As a reward for purchasing upfront, you'll
                        get a 10%-30% discount.
                    </p>

                    <p className="mb-0">
                        Based on your usage, we recommend purchasing{' '}
                        <b>
                            $
                            {(selfServeCreditEligibility.estimated_credit_amount_usd * 12).toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            })}
                        </b>{' '}
                        credits which equals $
                        {selfServeCreditEligibility.estimated_credit_amount_usd.toLocaleString('en-US', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                        })}{' '}
                        per month. The minimum purchase size for credits is $6,000 per year.
                    </p>

                    <p className="mb-1 text-md font-semibold">Breakdown</p>
                    <p>
                        Due today: <b>${Math.round(+selfServeCreditForm.creditInput).toLocaleString('en-US')}</b>
                        <br />
                        Discount: <b>{getDiscount() * 100}%</b>
                        <br />
                        Total credits:{' '}
                        <b>
                            $
                            {(+selfServeCreditForm.creditInput / (1 - getDiscount())).toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            })}
                        </b>
                        <br />
                        Monthly credits:{' '}
                        <b>
                            $
                            {(+selfServeCreditForm.creditInput / (1 - getDiscount()) / 12).toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            })}
                        </b>
                    </p>

                    <LemonField name="creditInput">
                        {({ value, onChange, error }) => (
                            <div className="max-w-40">
                                <LemonInput
                                    type="number"
                                    fullWidth={false}
                                    status={error ? 'danger' : 'default'}
                                    value={value}
                                    data-attr="credit-input"
                                    onChange={onChange}
                                    prefix={<b>$</b>}
                                    min={0}
                                    step={10}
                                    suffix={<>/ year</>}
                                    size="small"
                                />
                            </div>
                        )}
                    </LemonField>

                    <LemonDivider />
                    <p className="mb-1 text-md font-semibold">Invoice details</p>
                    <p className="mb-0">
                        We can either charge your card on file now or send you an invoice. Check the box below if you'd
                        like to receive an invoice. We will also close any existing open invoices.
                    </p>
                    <LemonField name="sendInvoice">
                        {({ value, onChange }) => (
                            <LemonCheckbox label="Send me an invoice" checked={value} onChange={onChange} />
                        )}
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}
