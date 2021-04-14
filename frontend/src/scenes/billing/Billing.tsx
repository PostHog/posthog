import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { CurrentPlan } from './CurrentPlan'
import { CurrentUsage } from './CurrentUsage'
import { BillingEnrollment } from './BillingEnrollment'
import { useValues } from 'kea'
import './Billing.scss'
import { billingLogic } from './billingLogic'

export function Billing(): JSX.Element {
    const { billing } = useValues(billingLogic)

    return (
        <div className="billing-page">
            <PageHeader title="Billing &amp; usage information" />
            <CurrentUsage />
            {billing?.plan ? <CurrentPlan plan={billing.plan} /> : <BillingEnrollment />}
            <div style={{ marginBottom: 128 }} />
        </div>
    )
}
