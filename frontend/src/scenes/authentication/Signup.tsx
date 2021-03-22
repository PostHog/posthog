import { Col, Row, Form, Input, Button, Alert } from 'antd'
import React from 'react'
import logo from 'public/posthog-logo-white.svg'
import './Signup.scss'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PasswordInput } from './PasswordInput'
import { CheckOutlined } from '@ant-design/icons'

export function Signup(): JSX.Element {
    const [form] = Form.useForm()
    const { preflight } = useValues(preflightLogic)
    const loading = false // TODO
    const errorResponse: Record<string, any> = {} // TODO
    const authenticate = (values: any): void => console.log(values) // TODO

    return (
        <div className="signup">
            <Row>
                <Col span={24} md={14} className="image-showcase-container">
                    <div className="image-showcase ant-col-24 ant-col-md-14">
                        <div className="main-logo">
                            <a href="https://posthog.com?utm_campaign=in-product&utm_tag=signup-header">
                                <img src={logo} alt="" />
                            </a>
                        </div>
                        <div className="planet" />
                        <div className="showcase-content">
                            <h1 className="page-title">Try PostHog Cloud!</h1>
                            <div className="showcase-description">
                                PostHog Cloud is the hosted version of our open source package.
                                <br />
                                <br />
                                We manage hosting, scaling and upgrades.
                                <div className="signup-list">
                                    <div>
                                        <CheckOutlined /> First 10k events free every month
                                    </div>
                                    <div>
                                        <CheckOutlined /> Pay per use, cancel anytime
                                    </div>
                                    <div>
                                        <CheckOutlined /> Community, Slack &amp; email support
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </Col>
                <Col span={24} md={10} className="auth-main-content">
                    <div className="inner">
                        <h2 className="subtitle" style={{ justifyContent: 'center' }}>
                            Get started
                        </h2>
                        <div className="text-center" style={{ marginBottom: 32 }}>
                            Already have an account?{' '}
                            <Link to="/login" data-attr="signup-login-link">
                                Sign in
                            </Link>
                        </div>
                        {!loading && errorResponse?.errorCode && (
                            <Alert
                                message="Could not complete your login"
                                description={errorResponse?.errorDetail}
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
                            <PasswordInput />
                            <Form.Item>
                                <Button
                                    type="primary"
                                    htmlType="submit"
                                    data-attr="password-signup"
                                    loading={loading}
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
                            <SocialLoginButtons displayStyle="link" caption="Or sign up with" />
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}
