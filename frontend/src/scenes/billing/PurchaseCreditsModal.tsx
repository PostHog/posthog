import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { BillingGauge } from './BillingGauge'
import { billingLogic } from './billingLogic'
import { DEFAULT_ESTIMATED_MONTHLY_CREDIT_AMOUNT_USD } from './CreditCTAHero'
import { BillingGaugeItemKind } from './types'

export const PurchaseCreditsModal = (): JSX.Element | null => {
    const { showPurchaseCreditsModal, submitCreditForm } = useActions(billingLogic)
    const { creditOverview, isCreditFormSubmitting, creditForm, creditDiscount } = useValues(billingLogic)
    const { openSupportForm } = useActions(supportLogic)

    const creditInputValue: number = +creditForm.creditInput || 0
    const estimatedMonthlyCreditAmountUsd =
        creditOverview.estimated_monthly_credit_amount_usd || DEFAULT_ESTIMATED_MONTHLY_CREDIT_AMOUNT_USD
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
                            ? `$${Math.round(creditInputValue - creditInputValue * creditDiscount).toLocaleString(
                                  'en-US',
                                  {
                                      minimumFractionDigits: 0,
                                      maximumFractionDigits: 0,
                                  }
                              )}`
                            : ''}{' '}
                        credits
                    </LemonButton>
                </>
            }
        >
            <Form formKey="creditForm" logic={billingLogic} enableFormOnSubmit>
                <div className="flex flex-col gap-3.5">
                    <p className="mb-0">
                        We're giving you the option to buy usage credits in advance at discount of up to 30%.
                    </p>

                    <p className="mb-0">
                        Based on your usage, we think you'll use{' '}
                        <b>
                            $
                            {(+estimatedMonthlyCreditAmountUsd).toLocaleString('en-US', {
                                minimumFractionDigits: 0,
                                maximumFractionDigits: 0,
                            })}
                        </b>{' '}
                        of credits per month, for a total of{' '}
                        <b>
                            $
                            {(+estimatedMonthlyCreditAmountUsd * 12).toLocaleString('en-US', {
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
                        items={[
                            {
                                type: BillingGaugeItemKind.FreeTier,
                                text:
                                    creditInputValue >= 3000 && creditInputValue < 20000 ? (
                                        <>
                                            <IconCheckCircle className="text-success-foreground" /> 10% off
                                        </>
                                    ) : (
                                        '10% off'
                                    ),
                                value: 3000,
                                prefix: '$',
                            },
                            {
                                type: BillingGaugeItemKind.FreeTier,
                                text:
                                    creditInputValue >= 20000 && creditInputValue < 60000 ? (
                                        <>
                                            <IconCheckCircle className="text-success-foreground" /> 20% off
                                        </>
                                    ) : (
                                        '20% off'
                                    ),
                                value: 20000,
                                prefix: '$',
                            },
                            {
                                type: BillingGaugeItemKind.FreeTier,
                                text:
                                    creditInputValue >= 60000 && creditInputValue < 100000 ? (
                                        <>
                                            <IconCheckCircle className="text-success-foreground" /> 25% off
                                        </>
                                    ) : (
                                        '25% off'
                                    ),
                                prefix: '$',
                                value: 60000,
                            },
                            {
                                type: BillingGaugeItemKind.FreeTier,
                                text:
                                    creditInputValue >= 100000 ? (
                                        <>
                                            <IconCheckCircle className="text-success-foreground" /> 35% off
                                        </>
                                    ) : (
                                        '35% off'
                                    ),
                                prefix: '$',
                                value: 100000,
                            },
                            {
                                type: BillingGaugeItemKind.CurrentUsage,
                                text: 'Credits purchased',
                                prefix: '$',
                                value: creditInputValue,
                            },
                        ]}
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
                                        <span className="line-through">
                                            $
                                            {creditInputValue.toLocaleString('en-US', {
                                                minimumFractionDigits: 0,
                                                maximumFractionDigits: 0,
                                            })}
                                        </span>
                                        <span className="italic">${creditDiscount * 100}% off</span>
                                    </span>
                                ),
                            },
                            {
                                item: 'Discount',
                                value: (
                                    <span className="text-success-foreground-light">
                                        -$
                                        {Math.round(creditInputValue * creditDiscount).toLocaleString('en-US', {
                                            minimumFractionDigits: 0,
                                            maximumFractionDigits: 0,
                                        })}
                                    </span>
                                ),
                            },
                            {
                                item: 'Due today',
                                value: (
                                    <span className="font-semibold">
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
