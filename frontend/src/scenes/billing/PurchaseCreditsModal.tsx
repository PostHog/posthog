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
            title="Level unlocked, you're eligible for a discount 🎉"
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
                        Purchase {creditForm.creditInput ? `$${creditForm.creditInput.toLocaleString()}` : ''} credits
                    </LemonButton>
                </>
            }
        >
            <Form formKey="creditForm" logic={billingLogic} enableFormOnSubmit>
                <div className="flex flex-col gap-3.5">
                    <p className="mb-0">Save up to 30% on your bill by purchasing credits up front.</p>

                    <p className="mb-0">
                        Based on your usage, we recommend purchasing{' '}
                        <b>
                            $
                            {(selfServeCreditOverview.estimated_monthly_credit_amount_usd * 12).toLocaleString(
                                'en-US',
                                {
                                    minimumFractionDigits: 0,
                                    maximumFractionDigits: 0,
                                }
                            )}
                        </b>{' '}
                        credits which equals $
                        {selfServeCreditOverview.estimated_monthly_credit_amount_usd.toLocaleString('en-US', {
                            minimumFractionDigits: 0,
                            maximumFractionDigits: 0,
                        })}{' '}
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
                                value: 100000,
                                top: true,
                            },
                            {
                                type: BillingGaugeItemKind.CurrentUsage,
                                text: 'Your input',
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
                                item: 'Due today',
                                value: `$${Math.round(+creditForm.creditInput).toLocaleString('en-US')}`,
                            },
                            {
                                item: 'Discount',
                                value: `${creditDiscount * 100}%`,
                            },
                            {
                                item: 'Total credits',
                                value: `$${(+creditForm.creditInput / (1 - creditDiscount)).toLocaleString('en-US', {
                                    minimumFractionDigits: 0,
                                    maximumFractionDigits: 0,
                                })}`,
                            },
                            {
                                item: 'Monthly credits',
                                value: `$${(+creditForm.creditInput / (1 - creditDiscount) / 12).toLocaleString(
                                    'en-US',
                                    {
                                        minimumFractionDigits: 0,
                                        maximumFractionDigits: 0,
                                    }
                                )}`,
                            },
                        ]}
                    />

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
