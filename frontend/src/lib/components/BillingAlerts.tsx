import React from 'react'
import { Link } from 'lib/components/Link'
import { useValues } from 'kea'
import { WarningOutlined, AlertOutlined } from '@ant-design/icons'
import { billingLogic, BillingAlertType } from 'scenes/billing/billingLogic'

export function BillingAlerts(): JSX.Element | null {
    const { billing, trialMissingDays } = useValues(billingLogic)
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
    if (alertToShow === BillingAlertType.TrialStarted) {
        message = (
            <p>
                <b>Welcome to PostHog!&nbsp;</b>
                <Link to="/organization/billing" data-attr="trial_started_find_out_more">
                    We've given you access to all premium features for {trialMissingDays}{' '}
                    {trialMissingDays > 1 ? 'days' : 'day'}. Find out more!
                </Link>
            </p>
        )
    }
    if (alertToShow === BillingAlertType.TrialOngoing) {
        message = (
            <p>
                <b>
                    Your trial of premium features ends in {trialMissingDays === 0 && 'less than 1 day'}
                    {trialMissingDays > 0 && `${trialMissingDays} ${trialMissingDays > 1 ? 'days' : 'day'}`}.&nbsp;
                </b>
                <Link to="/organization/billing" data-attr="trial_started_find_out_more">
                    Find out how to unlock them forever.
                </Link>
            </p>
        )
    }
    if (alertToShow === BillingAlertType.TrialExpired) {
        message = (
            <p>
                <b>You're on a limited plan.&nbsp;</b>
                <Link to="/organization/billing" data-attr="trial_expired_link">
                    {billing?.plan?.custom_setup_billing_message ||
                        'Find out how to get premium features back and get 1M events free each month.'}
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
            {isWarning && <WarningOutlined className="text-warning" style={{ paddingRight: '1rem' }} />}
            {isAlert && <AlertOutlined className="text-warning" style={{ paddingRight: '1rem' }} />}
            {message}
        </div>
    )
}
