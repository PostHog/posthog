import React from 'react'
import { WarningOutlined } from '@ant-design/icons'

const BillingToolbar = (props) => {
    const { billingUrl } = props

    return (
        <>
            {billingUrl && (
                <div className="card" style={{ marginBottom: '2rem' }}>
                    <div className="card-body">
                        <WarningOutlined className="text-danger" /> Hey! You have reached your usage limit for the Free
                        plan.{' '}
                        <a href={billingUrl} className="text-primary">
                            <b>Upgrade now</b>
                        </a>{' '}
                        to the Growth plan for $29/month and receive up to 500,000 events/month.
                    </div>
                </div>
            )}
        </>
    )
}

export default BillingToolbar
