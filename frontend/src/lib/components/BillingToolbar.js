import React from 'react'
import PropTypes from 'prop-types'
import { WarningOutlined, ToolFilled } from '@ant-design/icons'
import { Button } from 'antd'

const BillingToolbar = (props) => {
    const { billingUrl, message } = props
    return (
        <>
            {billingUrl && (
                <div className="card">
                    <div className="card-body" style={{ display: 'flex' }}>
                        <div style={{ flexGrow: '1', display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 8 }} />
                            {message}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <Button type="primary" href={billingUrl} icon={<ToolFilled />}>
                                Set up now
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}

BillingToolbar.propTypes = {
    billingUrl: PropTypes.string,
    message: PropTypes.string,
}

BillingToolbar.defaultProps = {
    billingUrl: null,
    message: 'Please set up your billing information.',
}

export default BillingToolbar
