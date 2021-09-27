import { Col, Row, Form, Input, Button } from 'antd'
import React from 'react'
import cloudLogo from 'public/posthog-logo-cloud.svg'
import selfHostedLogo from 'public/posthog-logo-selfhosted.svg'
import './Login.scss'
import { useActions, useValues } from 'kea'
import { loginLogic } from './loginLogic'
import { Link } from 'lib/components/Link'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PasswordInput } from './PasswordInput'
import { ERROR_MESSAGES } from 'lib/constants'
import { ExclamationCircleFilled } from '@ant-design/icons'
import clsx from 'clsx'
import { ErrorMessage } from 'lib/components/ErrorMessage/ErrorMessage'

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=login-header'

export function Login(): JSX.Element {
    const [form] = Form.useForm()
    const { authenticate } = useActions(loginLogic)
    const { authenticateResponseLoading, authenticateResponse } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <div className="bridge-page login">
            <Row>
                <Col span={24} className="auth-main-content">
                    <a href={`https://posthog.com?${UTM_TAGS}`}>
                        <div className="header-logo">
                            <img src={preflight?.cloud ? cloudLogo : selfHostedLogo} alt="PostHog Cloud" />
                        </div>
                    </a>
                    <div className="inner">
                        <h2 className="subtitle" style={{ justifyContent: 'center' }}>
                            Get started
                        </h2>
                        {!authenticateResponseLoading && authenticateResponse?.errorCode && (
                            <ErrorMessage style={{ marginBottom: 16 }}>
                                {authenticateResponse?.errorDetail ||
                                    ERROR_MESSAGES[authenticateResponse.errorCode] ||
                                    'Could not complete your login. Please try again.'}
                            </ErrorMessage>
                        )}
                        <Form
                            layout="vertical"
                            form={form}
                            onFinish={(values) => authenticate(values)}
                            requiredMark={false}
                            noValidate
                        >
                            <Form.Item
                                name="email"
                                label="Email"
                                rules={[
                                    {
                                        required: true,
                                        message: (
                                            <>
                                                <ExclamationCircleFilled style={{ marginLeft: 4 }} /> Please enter your
                                                email to continue
                                            </>
                                        ),
                                    },
                                ]}
                            >
                                <Input
                                    className="ph-ignore-input"
                                    autoFocus
                                    data-attr="login-email"
                                    placeholder="email@yourcompany.com"
                                    type="email"
                                />
                            </Form.Item>
                            <PasswordInput />
                            <Form.Item>
                                <Button
                                    className="btn-bridge"
                                    htmlType="submit"
                                    data-attr="password-signup"
                                    loading={authenticateResponseLoading}
                                    block
                                >
                                    Login
                                </Button>
                            </Form.Item>
                        </Form>
                        <div className={clsx('helper-links', { cloud: preflight?.cloud })}>
                            {preflight?.cloud && (
                                <Link to="/signup" data-attr="signup" className="lhs">
                                    Create an account
                                </Link>
                            )}
                            <a href="/accounts/password_reset/" data-attr="forgot-password" className="rhs">
                                Forgot your password?
                            </a>
                            &nbsp;
                        </div>
                        <SocialLoginButtons caption="Or log in with" />
                    </div>
                </Col>
            </Row>
        </div>
    )
}
