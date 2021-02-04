import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { CurrentPlan } from './CurrentPlan'
import { CurrentUsage } from './CurrentUsage'
import { BillingEnrollment } from './BillingEnrollment'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export function Billing(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <>
            <PageHeader title="Billing &amp; usage information" />
            <CurrentUsage />
            {user?.billing?.plan ? <CurrentPlan plan={user.billing.plan} /> : <BillingEnrollment />}
            <div style={{ marginBottom: 128 }} />
        </>
    )
}
