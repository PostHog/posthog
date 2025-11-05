import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { BillingGauge } from './BillingGauge'
import { billingLogic } from './billingLogic'
import { BillingGaugeItemKind } from './types'

function floatDiscountToText(discount: number): string {
    return `${Math.floor(discount * 100)}%`
}

function generateBillingGaugeItemsFromCreditBrackets(creditInputValue: number, creditBrackets: any[]): any[] {
    return [
        ...creditBrackets.map((bracket) => ({
            type: BillingGaugeItemKind.FreeTier,
            text:
                creditInputValue >= bracket.annual_credit_from_inclusive &&
                creditInputValue < (bracket.annual_credit_to_exclusive || Infinity) ? (
                    <>
                        <IconCheckCircle className="text-success" /> {floatDiscountToText(bracket.discount)} off
                    </>
                ) : (
                    `${floatDiscountToText(bracket.discount)} off`
                ),
            value: bracket.annual_credit_from_inclusive,
            prefix: '$',
        })),
        {
            type: BillingGaugeItemKind.CurrentUsage,
            text: 'Credits purchased',
            prefix: '$',
            value: creditInputValue,
        },
    ]
}

export const PurchaseCreditsModal = (): JSX.Element | null => {
    const { showPurchaseCreditsModal, submitCreditForm } = useActions(billingLogic)
    const {
        creditOverview,
        isCreditFormSubmitting,
        creditForm,
        creditDiscount,
        creditBrackets,
        estimatedMonthlyCreditAmountUsd,
    } = useValues(billingLogic)
    const { openSupportForm } = useActions(supportLogic)

    const creditInputValue: number = +creditForm.creditInput || 0
    const billingGaugeItems = generateBillingGaugeItemsFromCreditBrackets(creditInputValue, creditBrackets)
    const maxDiscount = Math.max(...creditBrackets.map((b) => b.discount))

    return (
        <LemonModal
            onClose={() => showPurchaseCreditsModal(false)}
            width="max(44vw)"
            title="Prepay for usage credits and get a discount"
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
                        Buy{' '}
                        {creditForm.creditInput
                            ? `$${Math.round(creditInputValue).toLocaleString('en-US', {
                                  minimumFractionDigits: 0,
                                  maximumFractionDigits: 0,
                              })}`
                            : ''}{' '}
                        credits {creditDiscount > 0 ? `at ${floatDiscountToText(creditDiscount)} off` : ''}
                    </LemonButton>
                </>
            }
        >
            <Form formKey="creditForm" logic={billingLogic} enableFormOnSubmit>
                <div className="flex flex-col gap-3.5">
                    <p className="mb-0">
                        We're giving you the option to buy usage credits in advance at discount of up to{' '}
                        {floatDiscountToText(maxDiscount)}.
                    </p>

                    <p className="mb-0">
                        Based on your usage, we think you'll use{' '}
                        <b>
                            $
                            {(+estimatedMonthlyCreditAmountUsd!).toLocaleString('en-US', {
                                minimumFractionDigits: 0,
                                maximumFractionDigits: 0,
                            })}
                        </b>{' '}
                        of credits per month, for a total of{' '}
                        <b>
                            $
                            {(+estimatedMonthlyCreditAmountUsd! * 12).toLocaleString('en-US', {
                                minimumFractionDigits: 0,
                                maximumFractionDigits: 0,
                            })}
                        </b>{' '}
                        credits for the year.
                    </p>

                    <LemonField
                        name="creditInput"
                        label="How many credits do you want to purchase?"
                        help="Credits are dispersed monthly and roll over to the next month. If you use more than the available credits in any month, you'll pay for the usage at the standard rate. Credits expire after 1 year from purchase."
                    >
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
                        items={billingGaugeItems}
                        // @ts-expect-error
                        product={{
                            percentage_usage: 0.3,
                        }}
                    />

                    <div>
                        <p className="mb-1 text-md font-semibold">Payment details</p>
                        <p className="mb-0">Choose how you'd like to pay for your credits.</p>
                    </div>
                    <LemonField name="collectionMethod">
                        {({ value, onChange }) => (
                            <LemonRadio
                                value={value}
                                onChange={onChange}
                                options={[
                                    {
                                        value: 'charge_automatically',
                                        label: creditOverview.cc_last_four
                                            ? `Pay with credit card on file (**** ${creditOverview.cc_last_four})`
                                            : 'Pay with credit card on file',
                                    },
                                    {
                                        value: 'send_invoice',
                                        label: creditOverview.email
                                            ? `Send me an invoice to ${creditOverview.email}`
                                            : 'Send me an invoice',
                                    },
                                ]}
                            />
                        )}
                    </LemonField>

                    <LemonDivider />

                    <div>
                        <p className="mb-1 text-md font-semibold">Summary</p>
                        <p className="mb-0">Here's a summary of what you'll pay.</p>
                    </div>
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
                                item: "Credits you'll receive",
                                value: (
                                    <span className="flex deprecated-space-x-2">
                                        $
                                        {creditInputValue.toLocaleString('en-US', {
                                            minimumFractionDigits: 0,
                                            maximumFractionDigits: 0,
                                        })}
                                    </span>
                                ),
                            },
                            {
                                item: 'Discount',
                                value: (
                                    <span className="text-success-light flex gap-1">
                                        -$
                                        {Math.round(creditInputValue * creditDiscount).toLocaleString('en-US', {
                                            minimumFractionDigits: 0,
                                            maximumFractionDigits: 0,
                                        })}
                                        <span className="italic text-secondary">${creditDiscount * 100}% off!</span>
                                    </span>
                                ),
                            },
                            {
                                item: 'Due today',
                                value: (
                                    <span className="font-semibold flex gap-1">
                                        $
                                        {Math.round(
                                            creditInputValue - creditInputValue * creditDiscount
                                        ).toLocaleString('en-US', {
                                            minimumFractionDigits: 0,
                                            maximumFractionDigits: 0,
                                        })}
                                    </span>
                                ),
                            },
                        ]}
                    />

                    <div className="flex gap-2">
                        Have questions?{' '}
                        <Link
                            onClick={() => {
                                showPurchaseCreditsModal(false)
                                openSupportForm({ kind: 'support', target_area: 'billing' })
                            }}
                        >
                            Get support
                        </Link>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
