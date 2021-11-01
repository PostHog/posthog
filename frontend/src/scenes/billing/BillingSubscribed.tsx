import { Button, Col, Row } from 'antd'
import React from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import './BillingSubscribed.scss'
import hedgehogMain from 'public/hedgehog-bridge-page.png'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { CheckCircleOutlined, CloseCircleOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { kea, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { billingSubscribedLogicType } from './BillingSubscribedType'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'

enum SubscriptionStatus {
    Success = 'success',
    Failed = 'failed',
}

const billingSubscribedLogic = kea<billingSubscribedLogicType<SubscriptionStatus>>({
    connect: {
        actions: [sceneLogic, ['setScene']],
    },
    actions: {
        setStatus: (status: SubscriptionStatus) => ({ status }),
        setSubscriptionId: (id: string) => ({ id }),
    },
    reducers: {
        status: [
            SubscriptionStatus.Failed,
            {
                setStatus: (_, { status }) => status,
            },
        ],
        subscriptionId: [
            null as string | null,
            {
                setSubscriptionId: (_, { id }) => id,
            },
        ],
    },
    listeners: ({ values }) => ({
        setScene: async (_, breakpoint) => {
            await breakpoint(100)
            if (values.status === SubscriptionStatus.Success) {
                sceneLogic.actions.setPageTitle('Subscribed!')
            } else {
                sceneLogic.actions.setPageTitle('Subscription failed')
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '*': (_, { s, subscription_id }) => {
            if (s === 'success') {
                actions.setStatus(SubscriptionStatus.Success)
            }
            if (subscription_id) {
                actions.setSubscriptionId(subscription_id)
            }
        },
    }),
})

export function BillingSubscribed(): JSX.Element {
    const { status } = useValues(billingSubscribedLogic)

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

function SubscriptionFailure(): JSX.Element {
    const { subscriptionId } = useValues(billingSubscribedLogic)
    return (
        <>
            <CloseCircleOutlined style={{ color: 'var(--danger)' }} className="title-icon" />
            <h2 className="subtitle">Something went wrong</h2>
            <p>
                We couldn't start your subscription. Please try again with a{' '}
                <b>different payment method or contact us</b> if the problem persists.
            </p>
            {subscriptionId && (
                // Note we include PostHog Cloud specifically (app.posthog.com) because billing can only be set up there.
                <Button
                    className="btn-bridge"
                    block
                    href={`https://app.posthog.com/billing/setup?session_id=${subscriptionId}`}
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
