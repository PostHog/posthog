import { Col, Row, Form, Input, Button, Skeleton, Divider } from 'antd'
import { ErrorMessage } from 'lib/components/ErrorMessage/ErrorMessage'
import React from 'react'
import { WelcomeLogo } from './WelcomeLogo'
import { ExclamationCircleFilled } from '@ant-design/icons'
import './PasswordReset.scss'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'

export function PasswordReset(): JSX.Element {
    const responseLoading = false // TODO
    const response: Record<string, any> = {} // TODO
    const reset = (vals: any): void => {
        console.log(vals)
    } // TODO
    const [form] = Form.useForm()
    const { preflight, preflightLoading } = useValues(preflightLogic)

    return (
        <div className="bridge-page password-reset">
            <Row>
                <Col span={24} className="auth-main-content">
                    <WelcomeLogo view="login" />
                    <div className="inner">
                        <h2 className="subtitle" style={{ justifyContent: 'center' }}>
                            Reset password
                        </h2>
                        {preflightLoading ? (
                            <Skeleton active paragraph={{ rows: 4 }} />
                        ) : !preflight?.email_service_available ? (
                            <EmailUnavailable />
                        ) : (
                            <>
                                <div className="text-center mb">
                                    Enter your email address. If it exists, you’ll receive an email with a reset link
                                    soon.
                                </div>
                                {!responseLoading && response?.errorCode && (
                                    <ErrorMessage style={{ marginBottom: 16 }}>
                                        {response.errorDetail ||
                                            'Could not complete your password reset request. Please try again.'}
                                    </ErrorMessage>
                                )}
                                <Form
                                    layout="vertical"
                                    form={form}
                                    onFinish={(values) => reset(values)}
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
                                                        <ExclamationCircleFilled style={{ marginLeft: 4 }} /> Please
                                                        enter your email to continue
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
                                        />
                                    </Form.Item>
                                    <Form.Item>
                                        <Button
                                            className="btn-bridge"
                                            htmlType="submit"
                                            data-attr="password-reset"
                                            loading={responseLoading}
                                            block
                                        >
                                            Continue
                                        </Button>
                                    </Form.Item>
                                </Form>
                            </>
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
                <CodeSnippet language={Language.Bash} hideCopyButton>
                    {'python manage.py changepassword [email]'}
                </CodeSnippet>
            </div>
        </div>
    )
}
