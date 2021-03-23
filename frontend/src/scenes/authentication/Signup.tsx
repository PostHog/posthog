import { Col, Row, Form, Input, Button, Alert, Grid } from 'antd'
import React from 'react'
import logo from 'public/posthog-logo-white.svg'
import './Signup.scss'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PasswordInput } from './PasswordInput'
import { CheckOutlined, CloudFilled, GithubFilled } from '@ant-design/icons'
import { IconRocket } from 'lib/components/icons'
import { Breakpoint } from 'antd/lib/_util/responsiveObserve'

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=signup-header'

export function Signup(): JSX.Element {
    const [form] = Form.useForm()
    const { useBreakpoint } = Grid
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
                                <div className="alt-options">
                                    <h3>Interested in self-hosting?</h3>
                                    <a
                                        href={`https://posthog.com/pricing?o=vpc&${UTM_TAGS}`}
                                        target="_blank"
                                        rel="noopener"
                                        className="alt-option"
                                    >
                                        <div>
                                            <CloudFilled />
                                        </div>
                                        <div>
                                            <b>Private cloud</b>
                                            <div>Managed deployments, maximum scalability</div>
                                        </div>
                                    </a>
                                    <a
                                        href={`https://posthog.com/docs/deployment?${UTM_TAGS}`}
                                        target="_blank"
                                        rel="noopener"
                                        className="alt-option"
                                    >
                                        <div>
                                            <GithubFilled />
                                        </div>
                                        <div>
                                            <b>Open source</b>
                                            <div>Deploy on your own infrastructure. Free forever.</div>
                                        </div>
                                    </a>
                                </div>
                            </div>
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
                            <PasswordInput />
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
