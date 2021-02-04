import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { CurrentPlan } from './CurrentPlan'
import { CurrentUsage } from './CurrentUsage'

export function Billing(): JSX.Element {
    return (
        <>
            <PageHeader title="Billing &amp; usage information" />
            <CurrentUsage />
            <CurrentPlan />
            <div style={{ marginBottom: 128 }} />
        </>
    )
}
