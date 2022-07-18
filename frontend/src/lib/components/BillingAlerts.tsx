import React from 'react'
import { Link } from 'lib/components/Link'
import { useValues } from 'kea'
import { WarningOutlined, AlertOutlined, ToolFilled } from '@ant-design/icons'
import { Button, Card } from 'antd'
import { billingLogic, BillingAlertType } from 'scenes/billing/billingLogic'
import { LinkButton } from './LinkButton'
import { LemonButton } from './LemonButton'

export function BillingAlerts(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { alertToShow, percentage, strokeColor } = useValues(billingLogic)

    if (!alertToShow) {
        return null
    }

    return (
        <>
            <div style={{ marginTop: '1.5rem' }} />
            {alertToShow === BillingAlertType.SetupBilling && (
                <Card>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 8 }} />
                            <b>Action needed!&nbsp;</b>
                            {billing?.plan?.custom_setup_billing_message ||
                                'Please finish setting up your billing information.'}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <Button type="primary" href={billing?.subscription_url} icon={<ToolFilled />}>
                                Set up now
                            </Button>
                        </div>
                    </div>
                </Card>
            )}
            {alertToShow === BillingAlertType.TrialExpired && (
                <Card>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 8 }} />
                            Your free trial has expired. To continue using all features,{' '}
                            <Link to="/organization/billing" data-attr="trial_expired_link">
                                {' '}
                                add your card details
                            </Link>
                            .
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <LemonButton to="/organization/billing" data-attr="trial_expired_button" type="primary">
                                Subscribe
                            </LemonButton>
                        </div>
                    </div>
                </Card>
            )}
            {alertToShow === BillingAlertType.UsageNearLimit && (
                <Card>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 16 }} />
                            <div>
                                <b>Warning!</b> Nearing the monthly limit of events or billing limit for your
                                organization. You have already used{' '}
                                <b style={{ color: typeof strokeColor === 'string' ? strokeColor : 'inherit' }}>
                                    {percentage && percentage * 100}%
                                </b>{' '}
                                of your event allocation this month. To avoid losing data or access to it,{' '}
                                <b>we recommend upgrading</b> your billing plan now.
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', paddingLeft: 16 }}>
                            <LinkButton type="primary" to="/organization/billing">
                                <ToolFilled /> Manage billing
                            </LinkButton>
                        </div>
                    </div>
                </Card>
            )}
            {alertToShow === BillingAlertType.UsageLimitExceeded && (
                <Card>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <AlertOutlined className="text-warning" style={{ paddingRight: 16 }} />
                            <div>
                                <b>Alert!</b> The monthly limit of events or billing limit for your organization has
                                been exceeded. To avoid losing data or access to it, <b>we recommend increasing</b> your
                                billing limit.
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', paddingLeft: 16 }}>
                            <LinkButton type="primary" to="/organization/billing">
                                <ToolFilled /> Manage billing
                            </LinkButton>
                        </div>
                    </div>
                </Card>
            )}
        </>
    )
}
