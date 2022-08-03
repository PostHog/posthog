import React from 'react'
import { useValues } from 'kea'
import { billingLogic, BillingAlertType } from 'scenes/billing/billingLogic'
import { Link } from 'lib/components/Link'
import { IconWarningAmber } from './icons'

export function BillingAlerts(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { alertToShow, percentage, strokeColor } = useValues(billingLogic)

    if (!alertToShow) {
        return null
    }
    let message: JSX.Element | undefined
    let isWarning = false
    let isAlert = false
    if (alertToShow === BillingAlertType.SetupBilling) {
        isWarning = true
        message = (
            <p>
                <b>Action needed!&nbsp;</b>
                <Link href={billing?.subscription_url} data-attr="alert_setup_billing">
                    {billing?.plan?.custom_setup_billing_message ||
                        'Please finish setting up your billing information.'}
                </Link>
            </p>
        )
    }

    if (alertToShow === BillingAlertType.UsageNearLimit) {
        isWarning = true
        message = (
            <p>
                <b>Warning!</b> You have already used{' '}
                <b style={{ color: typeof strokeColor === 'string' ? strokeColor : 'inherit' }}>
                    {percentage && percentage * 100}%
                </b>{' '}
                of your event allocation this month.{' '}
                <Link to="/organization/billing" data-attr="trial_expired_link">
                    {billing?.plan?.custom_setup_billing_message ||
                        'To avoid losing data or access to it, upgrade your billing plan now.'}
                </Link>
            </p>
        )
    }

    if (alertToShow === BillingAlertType.UsageLimitExceeded) {
        isAlert = true
        message = (
            <p>
                <b>Alert!</b> The monthly limit of events or billing limit for your organization has been exceeded.{' '}
                <Link to="/organization/billing" data-attr="trial_expired_link">
                    {billing?.plan?.custom_setup_billing_message ||
                        'To avoid losing data or access to it, increase your billing limit now.'}
                </Link>
            </p>
        )
    }

    return (
        <div className={'Announcement'}>
            {isWarning && <IconWarningAmber className="text-warning" style={{ paddingRight: '1rem' }} />}
            {isAlert && <IconWarningAmber className="text-warning" style={{ paddingRight: '1rem' }} />}
            {message}
        </div>
    )
}
