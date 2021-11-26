/*
Scene to request a password reset email.
*/
import { Col, Row, Form, Input, Button, Skeleton, Divider } from 'antd'
import { InlineMessage } from 'lib/components/InlineMessage/InlineMessage'
import React from 'react'
import { WelcomeLogo } from './WelcomeLogo'
import { ExclamationCircleFilled, CheckCircleOutlined } from '@ant-design/icons'
import './PasswordReset.scss'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { passwordResetLogic } from './passwordResetLogic'
import { router } from 'kea-router'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: PasswordReset,
    logic: passwordResetLogic,
}

export function PasswordReset(): JSX.Element {
    const { preflight, preflightLoading } = useValues(preflightLogic)
    const { resetResponse } = useValues(passwordResetLogic)

    return (
        <div className="bridge-page password-reset">
            <Row>
                <Col span={24} className="auth-main-content">
                    <WelcomeLogo view="login" />
                    <div className="inner">
                        {resetResponse?.success && (
                            <div className="text-center">
                                <CheckCircleOutlined style={{ color: 'var(--success)', fontSize: '4em' }} />
                            </div>
                        )}
                        <h2 className="subtitle" style={{ justifyContent: 'center' }}>
                            Reset password
                        </h2>
                        {preflightLoading ? (
                            <Skeleton active paragraph={{ rows: 4 }} />
                        ) : !preflight?.email_service_available ? (
                            <EmailUnavailable />
                        ) : resetResponse?.success ? (
                            <ResetSuccess />
                        ) : (
                            <ResetForm />
                        )}
                    </div>
                </Col>
            </Row>
        </div>
    )
}

function EmailUnavailable(): JSX.Element {
    return (
        <div>
            <div>
                Self-serve password reset is unavailable. Please <b>contact your instance administrator</b> to reset
                your password.
            </div>
            <Divider />
            <div className="mt">
                If you're an administrator:
                <ul>
                    <li>
                        Password reset is unavailable because email service is not configured.{' '}
                        <a href="https://posthog.com/docs/self-host/configure/email?utm_medium=in-product&utm_campaign=password-reset">
                            Read the docs
                        </a>{' '}
                        on how to set this up.
                    </li>
                    <li>To reset the password manually, run the following command in your instance.</li>
                </ul>
                <CodeSnippet language={Language.Bash} wrap>
                    {'python manage.py changepassword [account email]'}
                </CodeSnippet>
            </div>
        </div>
    )
}

function ResetForm(): JSX.Element {
    const { resetResponseLoading, resetResponse } = useValues(passwordResetLogic)
    const { reset } = useActions(passwordResetLogic)
    const [form] = Form.useForm()

    return (
        <>
            <div className="text-center mb">
                Enter your email address. If an account exists, you’ll receive an email with a password reset link soon.
            </div>
            {!resetResponseLoading && resetResponse?.errorCode && (
                <InlineMessage style={{ marginBottom: 16 }} type="danger">
                    {resetResponse.errorDetail || 'Could not complete your password reset request. Please try again.'}
                </InlineMessage>
            )}
            <Form
                layout="vertical"
                form={form}
                onFinish={(values) => reset({ email: values.email })}
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
                                    <ExclamationCircleFilled style={{ marginLeft: 4 }} /> Please enter your email to
                                    continue
                                </>
                            ),
                        },
                    ]}
                >
                    <Input
                        className="ph-ignore-input"
                        autoFocus
                        data-attr="reset-email"
                        placeholder="email@yourcompany.com"
                        type="email"
                        disabled={resetResponseLoading}
                    />
                </Form.Item>
                <Form.Item>
                    <Button
                        className="btn-bridge"
                        htmlType="submit"
                        data-attr="password-reset"
                        loading={resetResponseLoading}
                        block
                    >
                        Continue
                    </Button>
                </Form.Item>
            </Form>
        </>
    )
}

function ResetSuccess(): JSX.Element {
    const { resetResponse } = useValues(passwordResetLogic)
    const { push } = useActions(router)
    return (
        <div className="text-center">
            Request received successfully! If the email <b>{resetResponse?.email || 'you typed'}</b> exists, you’ll
            receive an email with a reset link soon.
            <div className="mt">
                <Button className="btn-bridge" data-attr="back-to-login" block onClick={() => push('/login')}>
                    Back to login
                </Button>
            </div>
        </div>
    )
}
