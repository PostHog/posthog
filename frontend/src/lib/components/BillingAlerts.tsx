import React from 'react'
import { useValues } from 'kea'
import { AlertOutlined, ToolFilled } from '@ant-design/icons'
import { billingLogic, BillingAlertType } from 'scenes/billing/billingLogic'
import { LinkButton } from './LinkButton'

export function BillingAlerts(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { alertToShow, percentage, strokeColor } = useValues(billingLogic)

    if (!alertToShow) {
        return null
    }

    return (
        <>
            <div className="p-6 mt-6 border rounded-lg flex items-center">
                <div className="flex items-center grow gap-4">
                    <AlertOutlined className="text-warning pr-4" />
                    <div className="flex grow">
                        {alertToShow === BillingAlertType.SetupBilling ? (
                            <>
                                <b>Action needed!&nbsp;</b>
                                {billing?.plan?.custom_setup_billing_message ||
                                    'Please finish setting up your billing information.'}
                            </>
                        ) : alertToShow === BillingAlertType.UsageNearLimit ? (
                            <div>
                                <b>Warning!</b> Nearing the monthly limit of events or billing limit for your
                                organization. You have already used{' '}
                                <b style={{ color: typeof strokeColor === 'string' ? strokeColor : 'inherit' }}>
                                    {percentage && percentage * 100}%
                                </b>{' '}
                                of your event allocation this month. To avoid losing data or access to it,{' '}
                                <b>we recommend upgrading</b> your billing plan now.
                            </div>
                        ) : alertToShow === BillingAlertType.UsageLimitExceeded ? (
                            <>
                                <b>Alert!</b> The monthly limit of events or billing limit for your organization has
                                been exceeded. To avoid losing data or access to it, <b>we recommend increasing</b> your
                                billing limit.
                            </>
                        ) : undefined}
                    </div>

                    <LinkButton
                        type="primary"
                        to={
                            alertToShow === BillingAlertType.SetupBilling
                                ? billing?.subscription_url
                                : '/organization/billing'
                        }
                    >
                        <ToolFilled /> {alertToShow === BillingAlertType.SetupBilling ? 'Set up now' : 'Manage billing'}
                    </LinkButton>
                </div>
            </div>
        </>
    )
}
