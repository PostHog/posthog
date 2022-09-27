import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { Plan } from './Plan'
import { CurrentUsage } from './CurrentUsage'
import { BillingEnrollment } from './BillingEnrollment'
import './Billing.scss'
import { billingLogic } from './billingLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton } from '@posthog/lemon-ui'
import { AlertMessage } from 'lib/components/AlertMessage'
import { useActions, useValues } from 'kea'
import { licenseLogic } from 'scenes/billing/license/licenseLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LicenseForms } from './license/LicenseForms'
import { LicensesTable } from './license/LicensesTable'

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function Billing(): JSX.Element {
    const { billing } = useValues(billingLogic)

    const { licenses, licensesLoading, isActivateLicenseSubmitting, showConfirmCancel, showLicenseDirectInput } =
        useValues(licenseLogic)
    const { deleteLicense, setShowConfirmCancel, setShowLicenseDirectInput } = useActions(licenseLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <div className="flex flex-col gap-6">
            <PageHeader title="Billing &amp; usage" />
            {billing?.should_setup_billing && (
                <AlertMessage
                    type="warning"
                    action={{
                        children: billing.subscription_url ? (
                            <a href={billing.subscription_url}>
                                <LemonButton>Finish setup</LemonButton>
                            </a>
                        ) : undefined,
                    }}
                >
                    Your plan is <b>currently inactive</b> as you haven't finished setting up your billing information.
                </AlertMessage>
            )}
            <div className="flex flex-row gap-4 flex-wrap justify-center">
                <div className="flex-1 space-y-4">
                    <CurrentUsage />
                    <LicensesTable />
                </div>
                <div className="shrink-0 space-y-4">
                    <LicenseForms />
                    {billing?.plan && !billing?.should_setup_billing ? (
                        <Plan plan={billing.plan} currentPlan />
                    ) : (
                        <BillingEnrollment />
                    )}
                </div>
            </div>
        </div>
    )
}
