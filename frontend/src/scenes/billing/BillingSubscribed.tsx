import { Button, Col, Row } from 'antd'
import React from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import './BillingSubscribed.scss'
import hedgehogMain from 'public/hedgehog-bridge-page.png'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { CheckCircleOutlined } from '@ant-design/icons'
import { useActions } from 'kea'
import { router } from 'kea-router'

export function BillingSubscribed(): JSX.Element {
    return (
        <div className="bridge-page billing-subscribed">
            <Row>
                <Col span={24} className="auth-main-content">
                    <img src={hedgehogMain} alt="" className="main-art" />
                    <div className="inner-wrapper">
                        <WelcomeLogo view="signup" />
                        <div className="inner">
                            <SubscriptionSuccess />
                            <div className="support-footer">
                                Have questions? <HelpButton customComponent={<a href="#">Get help</a>} />
                            </div>
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}

function SubscriptionSuccess(): JSX.Element {
    const { push } = useActions(router)
    return (
        <>
            <CheckCircleOutlined style={{ color: 'var(--success)' }} className="title-icon" />
            <h2 className="subtitle">You're all set!</h2>
            <p>
                You are now subscribed to the <b>Standard Plan</b>. Please reach out to{' '}
                <a href="mailto:hey@posthog.com">hey@posthog.com</a> if you have any billing questions.
            </p>
            <Button className="btn-bridge outlined" block onClick={() => push('/')}>
                Continue to PostHog
            </Button>
        </>
    )
}
