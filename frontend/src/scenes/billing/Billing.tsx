import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { CurrentPlan } from './CurrentPlan'
import { CurrentUsage } from './CurrentUsage'
import { BillingEnrollment } from './BillingEnrollment'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import './Billing.scss'

export function Billing(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <div className="billing-page">
            <PageHeader title="Billing &amp; usage information" />
            <CurrentUsage />
            {user?.billing?.plan ? <CurrentPlan plan={user.billing.plan} /> : <BillingEnrollment />}
            <div style={{ marginBottom: 128 }} />
        </div>
    )
}
