import { Col, Row, Form, Input, Button, Alert, Grid } from 'antd'
import React from 'react'
import logo from 'public/posthog-logo-white.svg'
import './Signup.scss'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PasswordInput } from './PasswordInput'
import { IconRocket } from 'lib/components/icons'
import { Breakpoint } from 'antd/lib/_util/responsiveObserve'
import { SignupSideContentCloud, SignupSideContentHosted } from './SignupSideContent'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=signup-header'

export function Signup(): JSX.Element {
    const [form] = Form.useForm()
    const { useBreakpoint } = Grid
    const { preflight } = useValues(preflightLogic)
    const loading = false // TODO
    const errorResponse: Record<string, any> = {} // TODO
    const authenticate = (values: any): void => console.log(values) // TODO
    const screens = useBreakpoint()
    const isSmallScreen = (Object.keys(screens) as Breakpoint[]).filter((key) => screens[key]).length <= 2 // xs; sm

    return (
        <div className="signup">
            <Row>
                <Col span={24} lg={14} className="image-showcase-container" order={isSmallScreen ? 2 : undefined}>
                    <div className="image-showcase ant-col-24 ant-col-lg-14">
                        <div className="planet" />
                    </div>

                    <div className="showcase-content">
                        <div className="main-logo">
                            <a href={`https://posthog.com?${UTM_TAGS}`}>
                                <img src={logo} alt="" />
                            </a>
                        </div>
                        <div className="inner">
                            {preflight?.cloud ? (
                                <SignupSideContentCloud utm_tags={UTM_TAGS} />
                            ) : (
                                <SignupSideContentHosted utm_tags={UTM_TAGS} />
                            )}
                        </div>
                    </div>
                </Col>
                <Col span={24} lg={10} className="auth-main-content" order={isSmallScreen ? 1 : undefined}>
                    <div className="main-logo mobile-logo">
                        <a href={`https://posthog.com?${UTM_TAGS}`}>
                            <img src={logo} alt="" />
                        </a>
                    </div>
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
                            <PasswordInput showStrengthIndicator />
                            <Form.Item className="text-center">
                                By creating an account, you agree to our{' '}
                                <a href={`https://posthog.com/terms?${UTM_TAGS}`} target="_blank" rel="noopener">
                                    Terms of Service
                                </a>{' '}
                                and{' '}
                                <a href={`https://posthog.com/privacy?${UTM_TAGS}`} target="_blank" rel="noopener">
                                    Privacy Policy
                                </a>
                                .
                            </Form.Item>
                            <Form.Item>
                                <Button
                                    className="signup-submit"
                                    htmlType="submit"
                                    data-attr="password-signup"
                                    loading={loading}
                                    block
                                >
                                    <span className="icon">
                                        <IconRocket />
                                    </span>
                                    Create Account
                                </Button>
                            </Form.Item>
                        </Form>
                        <div style={{ marginTop: 48 }}>
                            <SocialLoginButtons displayStyle="link" caption="Or sign up with" />
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}
