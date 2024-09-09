import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { BillingGauge } from './BillingGauge'
import { billingLogic } from './billingLogic'
import { BillingGaugeItemKind } from './types'

export const PurchaseCreditsModal = (): JSX.Element | null => {
    const { showPurchaseCreditsModal, submitCreditForm } = useActions(billingLogic)
    const { selfServeCreditOverview, isCreditFormSubmitting, creditForm, creditDiscount } = useValues(billingLogic)

    return (
        <LemonModal
            onClose={() => showPurchaseCreditsModal(false)}
            width="max(44vw)"
            title="Buy credits in advance, get a discount"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => showPurchaseCreditsModal(false)}
                        disabled={isCreditFormSubmitting}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => submitCreditForm()} loading={isCreditFormSubmitting}>
                        Buy {creditForm.creditInput ? `$${creditForm.creditInput.toLocaleString()}` : ''} credits
                    </LemonButton>
                </>
            }
        >
            <Form formKey="creditForm" logic={billingLogic} enableFormOnSubmit>
                <div className="flex flex-col gap-3.5">
                    <p className="mb-0">
                        We're giving you the option to buy credits in advance at discount of up to 30%.
                    </p>

                    <p className="mb-0">
                        Based on your usage, we think you'll need{' '}
                        <b>
                            $
                            {(+selfServeCreditOverview.estimated_monthly_credit_amount_usd * 12).toLocaleString(
                                'en-US',
                                {
                                    minimumFractionDigits: 0,
                                    maximumFractionDigits: 0,
                                }
                            )}
                        </b>{' '}
                        credits this year. That's{' '}
                        <b>
                            $
                            {(+selfServeCreditOverview.estimated_monthly_credit_amount_usd).toLocaleString('en-US', {
                                minimumFractionDigits: 0,
                                maximumFractionDigits: 0,
                            })}
                        </b>{' '}
                        per month.
                    </p>

                    <LemonField name="creditInput" label="How many credits do you want to purchase?">
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

                    <BillingGauge
                        items={[
                            {
                                type: BillingGaugeItemKind.FreeTier,
                                text:
                                    +creditForm.creditInput >= 6000 && +creditForm.creditInput < 20000 ? (
                                        <>
                                            <IconCheckCircle className="text-success" /> 10% off
                                        </>
                                    ) : (
                                        '10% off'
                                    ),
                                value: 6000,
                                prefix: '$',
                                top: true,
                            },
                            {
                                type: BillingGaugeItemKind.FreeTier,
                                text:
                                    +creditForm.creditInput >= 20000 && +creditForm.creditInput < 60000 ? (
                                        <>
                                            <IconCheckCircle className="text-success" /> 20% off
                                        </>
                                    ) : (
                                        '20% off'
                                    ),
                                value: 20000,
                                prefix: '$',
                                top: true,
                            },
                            {
                                type: BillingGaugeItemKind.FreeTier,
                                text:
                                    +creditForm.creditInput >= 60000 && +creditForm.creditInput < 100000 ? (
                                        <>
                                            <IconCheckCircle className="text-success" /> 25% off
                                        </>
                                    ) : (
                                        '25% off'
                                    ),
                                prefix: '$',
                                value: 60000,
                                top: true,
                            },
                            {
                                type: BillingGaugeItemKind.FreeTier,
                                text:
                                    +creditForm.creditInput >= 100000 ? (
                                        <>
                                            <IconCheckCircle className="text-success" /> 30% off
                                        </>
                                    ) : (
                                        '30% off'
                                    ),
                                prefix: '$',
                                value: 100000,
                                top: true,
                            },
                            {
                                type: BillingGaugeItemKind.CurrentUsage,
                                text: 'Credits purchased',
                                prefix: '$',
                                value: +creditForm.creditInput,
                                top: false,
                            },
                        ]}
                        // @ts-expect-error
                        product={{
                            percentage_usage: 0.3,
                        }}
                    />

                    <LemonTable
                        showHeader={false}
                        columns={[
                            {
                                title: '',
                                dataIndex: 'item',
                            },
                            {
                                title: '',
                                dataIndex: 'value',
                            },
                        ]}
                        dataSource={[
                            {
                                item: "Total credits you'll receive",
                                value: `$${(+creditForm.creditInput / (1 - creditDiscount)).toLocaleString('en-US', {
                                    minimumFractionDigits: 0,
                                    maximumFractionDigits: 0,
                                })}`,
                            },
                            {
                                item: 'Discount',
                                value: `${creditDiscount * 100}%`,
                            },
                            {
                                item: 'Due today',
                                value: `$${Math.round(+creditForm.creditInput).toLocaleString('en-US')}`,
                            },
                        ]}
                    />

                    <LemonDivider />
                    <p className="mb-1 text-md font-semibold">Payment details</p>
                    <p className="mb-0">
                        Check the box if you want an invoice, otherwise we'll charge your card now. We'll also close any
                        open invoices.
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
