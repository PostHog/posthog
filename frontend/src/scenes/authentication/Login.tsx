import { Col, Row, Form, Input, Button } from 'antd'
import React from 'react'
import './Login.scss'
import { useActions, useValues } from 'kea'
import { loginLogic } from './loginLogic'
import { Link } from 'lib/components/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PasswordInput } from './PasswordInput'
import { ExclamationCircleFilled } from '@ant-design/icons'
import clsx from 'clsx'
import { InlineMessage } from 'lib/components/InlineMessage/InlineMessage'
import { WelcomeLogo } from './WelcomeLogo'
import { SceneExport } from 'scenes/sceneTypes'

export const ERROR_MESSAGES: Record<string, string | JSX.Element> = {
    no_new_organizations:
        'Your email address is not associated with an account. Please ask your administrator for an invite.',
    invalid_sso_provider: (
        <>
            The SSO provider you specified is invalid. Visit{' '}
            <a href="https://posthog.com/sso" target="_blank">
                https://posthog.com/sso
            </a>{' '}
            for details.
        </>
    ),
    improperly_configured_sso: (
        <>
            Cannot login with SSO provider because the provider is not configured, or your instance does not have the
            required license. Please visit{' '}
            <a href="https://posthog.com/sso" target="_blank">
                https://posthog.com/sso
            </a>{' '}
            for details.
        </>
    ),
}

export const scene: SceneExport = {
    component: Login,
    logic: loginLogic,
}

export function Login(): JSX.Element {
    const [form] = Form.useForm()
    const { authenticate, precheck } = useActions(loginLogic)
    const { authenticateResponseLoading, authenticateResponse, precheckResponse, precheckResponseLoading } =
        useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <div className="bridge-page login">
            <Row>
                <Col span={24} className="auth-main-content">
                    <WelcomeLogo view="login" />
                    <div className="inner">
                        <h2 className="subtitle" style={{ justifyContent: 'center' }}>
                            Get started
                        </h2>
                        {!authenticateResponseLoading && authenticateResponse?.errorCode && (
                            <InlineMessage style={{ marginBottom: 16 }} type="danger">
                                {authenticateResponse?.errorDetail ||
                                    ERROR_MESSAGES[authenticateResponse.errorCode] ||
                                    'Could not complete your login. Please try again.'}
                            </InlineMessage>
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
                                    onBlur={() => precheck({ email: form.getFieldValue('email') })}
                                />
                            </Form.Item>
                            <div className={clsx('password-wrapper', !precheckResponse && 'hidden')}>
                                <PasswordInput />
                            </div>
                            <Form.Item>
                                <Button
                                    className="btn-bridge"
                                    htmlType="submit"
                                    data-attr="password-signup"
                                    loading={authenticateResponseLoading || precheckResponseLoading}
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
                            <Link to="/reset" data-attr="forgot-password" className="rhs">
                                Forgot your password?
                            </Link>
                        </div>
                        <SocialLoginButtons caption="Or log in with" />
                    </div>
                </Col>
            </Row>
        </div>
    )
}
