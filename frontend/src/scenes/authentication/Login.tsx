import { Col, Row, Form, Input, Button, Alert } from 'antd'
import React from 'react'
import smLogo from 'public/icon-white.svg'
import './Login.scss'
import { useActions, useValues } from 'kea'
import { loginLogic } from './loginLogic'
import { Link } from 'lib/components/Link'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'

export function Login(): JSX.Element {
    const [form] = Form.useForm()
    const { authenticate } = useActions(loginLogic)
    const { authenticateResponseLoading, authenticateResponse } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <div className="login">
            <Row>
                <Col span={24} md={10} className="image-showcase-container">
                    <div className="image-showcase ant-col-24 ant-col-md-10">
                        <div className="the-mountains" />
                        <div className="main-logo">
                            <img src={smLogo} alt="" />
                        </div>
                        <div className="showcase-content">
                            <h1 className="page-title">Welcome back to PostHog!</h1>
                        </div>
                    </div>
                </Col>
                <Col span={24} md={14} className="auth-main-content">
                    <div className="inner">
                        <h2 className="subtitle" style={{ justifyContent: 'center' }}>
                            Login to PostHog
                        </h2>
                        {!authenticateResponseLoading && authenticateResponse?.errorCode && (
                            <Alert
                                message="Could not complete your login"
                                description={authenticateResponse?.errorDetail}
                                type="error"
                                showIcon
                                style={{ marginBottom: 16 }}
                            />
                        )}
                        <Form
                            layout="vertical"
                            form={form}
                            onFinish={(values) => authenticate(values)}
                            requiredMark={false}
                        >
                            <Form.Item
                                name="email"
                                label="Email"
                                rules={[
                                    {
                                        required: true,
                                        message: 'Please enter your email to continue',
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
                            <Form.Item
                                name="password"
                                label="Password"
                                rules={[
                                    {
                                        required: true,
                                        message: 'Please enter your password to continue',
                                    },
                                ]}
                            >
                                <Input
                                    className="ph-ignore-input"
                                    type="password"
                                    data-attr="login-password"
                                    placeholder="********"
                                />
                            </Form.Item>
                            <Form.Item>
                                <Button
                                    type="primary"
                                    htmlType="submit"
                                    data-attr="password-signup"
                                    loading={authenticateResponseLoading}
                                    block
                                >
                                    Login
                                </Button>
                            </Form.Item>
                        </Form>
                        <div className="text-center">
                            <a href="https://app.posthog.com/accounts/password_reset/" data-attr="forgot-password">
                                Forgot your password?
                            </a>
                        </div>
                        {preflight?.cloud && (
                            <div className="text-center mt">
                                Don't have an account? <Link to="/signup">Sign up now</Link>
                            </div>
                        )}
                        <div style={{ marginTop: 48 }}>
                            <SocialLoginButtons displayStyle="link" caption="Or login with" />
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}
