import { Button, Col, Row } from 'antd'
import React, { PropsWithChildren } from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import './BillingSubscribed.scss'
import hedgehogMain from 'public/hedgehog-bridge-page.png'
import { helpButtonLogic } from 'lib/components/HelpButton/HelpButton'
import { CheckCircleOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { SceneExport } from 'scenes/sceneTypes'
import { dayjs } from 'lib/dayjs'
import { billingLogic } from './billingLogic'
import { LemonButton } from '@posthog/lemon-ui'

export const scene: SceneExport = {
    component: BillingSubscribed,
}

export function BillingSubscribedTheme({ children }: PropsWithChildren<unknown>): JSX.Element {
    const { toggleHelp } = useActions(helpButtonLogic)

    return (
        <div className="bridge-page billing-subscribed">
            <Row>
                <Col span={24} className="auth-main-content">
                    <img src={hedgehogMain} alt="" className="main-art" />
                    <div className="inner-wrapper">
                        <WelcomeLogo view="signup" />
                        <div className="inner">
                            {children}
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

export function BillingSubscribed(): JSX.Element {
    const { push } = useActions(router)
    const { billing } = useValues(billingLogic)

    return (
        <BillingSubscribedTheme>
            <div className="title">
                <CheckCircleOutlined style={{ color: 'var(--success)' }} className="title-icon" />
                <h2 className="subtitle">You're all set!</h2>
            </div>
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
                    You will be billed on each month on the <strong>{dayjs().format('D')}</strong>. If you ingest less
                    than 1M events, you will not be billed.
                </p>
            )}
            <p>
                Please reach out to <a href="mailto:hey@posthog.com">hey@posthog.com</a> if you have any billing
                questions.
            </p>
            <LemonButton className="cta-button" type="primary" size="large" center={true} onClick={() => push('/')}>
                Finish
            </LemonButton>
        </BillingSubscribedTheme>
    )
}
