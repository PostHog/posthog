import { Button, Col, Row } from 'antd'
import React from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import './BillingSubscribed.scss'
import hedgehogMain from 'public/hedgehog-bridge-page.png'
import { helpButtonLogic } from 'lib/components/HelpButton/HelpButton'
import { CheckCircleOutlined, CloseCircleOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Link } from 'lib/components/Link'
import { billingSubscribedLogic, SubscriptionStatus } from './billingSubscribedLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: BillingSubscribed,
    logic: billingSubscribedLogic,
}

export function BillingSubscribed(): JSX.Element {
    const { status } = useValues(billingSubscribedLogic)
    const { toggleHelp } = useActions(helpButtonLogic)

    return (
        <div className="bridge-page billing-subscribed">
            <Row>
                <Col span={24} className="auth-main-content">
                    <img src={hedgehogMain} alt="" className="main-art" />
                    <div className="inner-wrapper">
                        <WelcomeLogo view="signup" />
                        <div className="inner">
                            {status === SubscriptionStatus.Success ? <SubscriptionSuccess /> : <SubscriptionFailure />}
                            <div className="support-footer">
                                Have questions?{' '}
                                <Button type="link" onClick={toggleHelp} style={{ paddingLeft: 0 }}>
                                    Get help
                                </Button>
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
    const { billing } = useValues(billingSubscribedLogic)

    return (
        <>
            <CheckCircleOutlined style={{ color: 'var(--success)' }} className="title-icon" />
            <h2 className="subtitle">You're all set!</h2>
            <p>
                You are now subscribed
                {billing?.is_billing_active && billing.plan && (
                    <>
                        {' '}
                        to the <b>{billing.plan.name}</b>
                    </>
                )}{' '}
                and can use all the premium features immediately.
            </p>
            {billing?.plan?.key === 'standard' && (
                <p className="text-muted-alt">
                    You will be billed within the <b>first 3 days of each month</b>. If you ingest less than 1M events,
                    you will not be billed.
                </p>
            )}
            <p>
                Please reach out to <a href="mailto:hey@posthog.com">hey@posthog.com</a> if you have any billing
                questions.
            </p>
            <Button className="btn-bridge outlined" block onClick={() => push('/')}>
                Finish
            </Button>
        </>
    )
}

function SubscriptionFailure(): JSX.Element {
    const { sessionId } = useValues(billingSubscribedLogic)
    return (
        <>
            <CloseCircleOutlined style={{ color: 'var(--danger)' }} className="title-icon" />
            <h2 className="subtitle">Something went wrong</h2>
            <p>
                We couldn't start your subscription. Please try again with a{' '}
                <b>different payment method or contact us</b> if the problem persists.
            </p>
            {sessionId && (
                /* Note we include PostHog Cloud specifically (app.posthog.com) in case a self-hosted user 
                ended up here for some reason. Should not happen as these should be processed by license.posthog.com */
                <Button
                    className="btn-bridge"
                    block
                    href={`https://app.posthog.com/billing/setup?session_id=${sessionId}`}
                >
                    Try again
                </Button>
            )}
            <div className="mt text-center">
                <Link to="/">
                    Go to PostHog <ArrowRightOutlined />
                </Link>
            </div>
        </>
    )
}
