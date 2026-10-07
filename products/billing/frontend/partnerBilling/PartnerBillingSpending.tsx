import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { PartnerBillingDetail } from './PartnerBillingDetail'
import { PartnerBillingLimitFields } from './PartnerBillingLimitFields'
import { PartnerBillingLogicProps, partnerBillingLogic } from './partnerBillingLogic'

export function PartnerBillingSpending({ applicationId }: PartnerBillingLogicProps): JSX.Element {
    const logic = partnerBillingLogic({ applicationId })
    const { payer, defaultLimitProducts, billingLoading, isSpendingFormSubmitting, spendingFormHasChanges } =
        useValues(logic)
    const { saveSpendingSettings } = useActions(logic)
    // Billing cannot store a spend alert or cap until the status reports spend, so the page offers neither.
    const spend = payer?.spend

    return (
        <section className="flex flex-col gap-4">
            <div>
                <h3 className="text-base font-semibold mb-1">Spending</h3>
                <p className="text-secondary text-sm mb-0">
                    {spend
                        ? 'Spend adds up across every organization you pay for. Amounts are in US dollars.'
                        : 'Amounts are in US dollars.'}
                </p>
            </div>
            {spend && (
                <PartnerBillingDetail label="Spend this month">
                    {spend.month_to_date_usd != null ? (
                        <span className="text-2xl font-semibold">{humanFriendlyCurrency(spend.month_to_date_usd)}</span>
                    ) : (
                        <span className="text-secondary">Not counted yet</span>
                    )}
                </PartnerBillingDetail>
            )}
            <Form
                logic={partnerBillingLogic}
                props={{ applicationId }}
                formKey="spendingForm"
                onSubmit={(event) => {
                    event.preventDefault()
                    saveSpendingSettings()
                }}
                className="flex flex-col gap-6"
            >
                {spend && (
                    <div className="flex flex-wrap gap-4">
                        <LemonField
                            name="spend_alert_usd"
                            label="Spend alert"
                            help="Billing sends an alert when spend this month reaches this amount."
                            className="w-60"
                        >
                            <LemonInput
                                prefix={<b>$</b>}
                                inputMode="decimal"
                                placeholder="No alert"
                                data-attr="partner-billing-spend-alert"
                            />
                        </LemonField>
                        <LemonField
                            name="spend_cap_usd"
                            label="Spend cap"
                            help="Billing limits further paid usage after reported spend reaches this amount. Reporting and enforcement delays can allow spend to exceed it."
                            className="w-60"
                        >
                            <LemonInput
                                prefix={<b>$</b>}
                                inputMode="decimal"
                                placeholder="No cap"
                                data-attr="partner-billing-spend-cap"
                            />
                        </LemonField>
                    </div>
                )}
                <div className="flex flex-col gap-2">
                    <div>
                        <LemonLabel>Default monthly limits per product</LemonLabel>
                        <p className="text-secondary text-xs mb-0">
                            A default limit applies to every organization you pay for that doesn't have its own limit
                            for that product. Set one organization's limits from the organizations table.
                        </p>
                    </div>
                    <PartnerBillingLimitFields
                        fieldName="default_limits_usd"
                        products={defaultLimitProducts}
                        productsLoading={billingLoading}
                    />
                </div>
                <div>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isSpendingFormSubmitting}
                        disabledReason={!spendingFormHasChanges ? 'No changes to save' : undefined}
                        data-attr="partner-billing-save-spending"
                    >
                        Save spending settings
                    </LemonButton>
                </div>
            </Form>
        </section>
    )
}
