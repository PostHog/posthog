import React from 'react'
import { Card, Progress } from 'antd'

function Billing() {
    const percentage = 0.31
    let strokeColor = '#1890FF'
    if (percentage === null || percentage === undefined) {
        /* No limit set */
        strokeColor = {
            from: '#1890FF',
            to: '#52C41A',
        }
    }

    if (percentage > 0.65 && percentage < 0.8) {
        strokeColor = '#F7A501'
    }
    if (percentage > 0.8) {
        strokeColor = '#F54E00'
    }

    return (
        <>
            <h1 className="page-header">Billing &amp; usage information</h1>
            <div className="space-top"></div>
            <Card title="Current usage">
                Your organization has used <b>3.1k</b> events this month. Your current plan has an allowance of up to{' '}
                <b>10k</b> events per month.
                <Progress type="line" percent={percentage ? percentage * 100 : 100} strokeColor={strokeColor} />
            </Card>
            <div className="space-top"></div>
            <Card title="Billing plan">
                Your organization is currently on the <b>Startup Plan</b>. We're working on allowing self-serve billing
                management, in the meantime, please{' '}
                <a href="mailto:hey@posthog.com?subject=Billing%20management">contact us</a> if you wish to change or
                cancel your subscription.
            </Card>
        </>
    )
}

export default Billing
