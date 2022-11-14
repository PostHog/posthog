import { useValues } from 'kea'
import { billingLogic, BillingAlertType } from 'scenes/billing/billingLogic'
import { Link } from 'lib/components/Link'
import { IconWarning } from './icons'
import clsx from 'clsx'

export function BillingAlerts(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { alertToShow, percentage, strokeColor } = useValues(billingLogic)

    if (!alertToShow) {
        return null
    }
    let message: JSX.Element | undefined
    let isWarning = false
    let isAlert = false

    if (percentage && alertToShow === BillingAlertType.FreeUsageNearLimit) {
        isWarning = true
        message = (
            <p>
                <b>Warning!</b> You have already used <b className="text-warning">{percentage * 100}%</b> of your 1
                million free events this month.{' '}
                <Link to="/organization/billing" data-attr="alert_free_usage_near_limit">
                    {billing?.plan?.custom_setup_billing_message ||
                        'To avoid losing data or access to it, upgrade your billing plan now.'}
                </Link>
            </p>
        )
    }

    if (billing?.subscription_url && alertToShow === BillingAlertType.SetupBilling) {
        isWarning = true
        message = (
            <p>
                <b>Action needed!&nbsp;</b>
                <Link to={billing.subscription_url} data-attr="alert_setup_billing">
                    {billing?.plan?.custom_setup_billing_message ||
                        'Please finish setting up your billing information.'}
                </Link>
            </p>
        )
    }

    if (percentage && alertToShow === BillingAlertType.UsageNearLimit) {
        isWarning = true
        message = (
            <p>
                <b>Warning!</b> You have already used {/* eslint-disable-next-line react/forbid-dom-props */}
                <b style={{ color: typeof strokeColor === 'string' ? strokeColor : 'inherit' }}>
                    {percentage * 100}%
                </b>{' '}
                of your event allocation this month.{' '}
                <Link to="/organization/billing" data-attr="alert_usage_near_limit">
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
                <Link to="/organization/billing" data-attr="alert_usage_limit_exceeded">
                    {billing?.plan?.custom_setup_billing_message ||
                        'To avoid losing data or access to it, increase your billing limit now.'}
                </Link>
            </p>
        )
    }

    return (
        <div className="Announcement">
            {isWarning || isAlert ? (
                <IconWarning className={clsx('text-lg mr-2', isWarning && 'text-warning', isAlert && 'text-danger')} />
            ) : null}
            {message}
        </div>
    )
}
