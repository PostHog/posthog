import { Col, Row } from 'antd'
import React from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import './BillingSubscribed.scss'
import hedgehogMain from 'public/hedgehog-bridge-page.png'

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
                            <div className="support-footer" />
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}

function SubscriptionSuccess(): JSX.Element {
    return (
        <>
            <h2 className="subtitle">You're all set!</h2>
            <p>
                You are now subscribed to the <b>Standard Plan</b>. Please reach out to{' '}
                <a href="mailto:hey@posthog.com">hey@posthog.com</a> if you have any billing questions.
            </p>
        </>
    )
}
