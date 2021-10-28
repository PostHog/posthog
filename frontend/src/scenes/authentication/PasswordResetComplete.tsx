/*
Scene to enter a new password from a received reset link
*/
import { Col, Row, Form, Button, Skeleton } from 'antd'
import React from 'react'
import { WelcomeLogo } from './WelcomeLogo'
import './PasswordReset.scss'
import { ErrorMessage } from 'lib/components/ErrorMessage/ErrorMessage'
import { PasswordInput } from './PasswordInput'
import { ExclamationCircleFilled, StopOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { passwordResetLogic } from './passwordResetLogic'
import { router } from 'kea-router'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: PasswordResetComplete,
    logic: passwordResetLogic,
}

export function PasswordResetComplete(): JSX.Element {
    const { validatedResetToken, validatedResetTokenLoading } = useValues(passwordResetLogic)
    const invalidLink = !validatedResetTokenLoading && !validatedResetToken?.success
    return (
        <div className="bridge-page password-reset-complete">
            <Row>
                <Col span={24} className="auth-main-content">
                    <WelcomeLogo view="login" />
                    <div className="inner">
                        {invalidLink && (
                            <div className="text-center">
                                <StopOutlined style={{ color: 'var(--muted)', fontSize: '4em' }} />
                            </div>
                        )}
                        <h2 className="subtitle" style={{ justifyContent: 'center' }}>
                            {invalidLink ? 'Unable to reset' : 'Set a new password'}
                        </h2>
                        {validatedResetTokenLoading ? (
                            <Skeleton paragraph={{ rows: 2 }} />
                        ) : !validatedResetToken?.token ? (
                            <ResetInvalid />
                        ) : (
                            <NewPasswordForm />
                        )}
                    </div>
                </Col>
            </Row>
        </div>
    )
}

function NewPasswordForm(): JSX.Element {
    const [form] = Form.useForm()
    const { updatePassword } = useActions(passwordResetLogic)
    const { newPasswordResponse, newPasswordResponseLoading } = useValues(passwordResetLogic)

    return (
        <>
            <div className="text-center mb">Please enter a new password for your account.</div>
            {!newPasswordResponseLoading && newPasswordResponse?.errorCode && (
                <ErrorMessage style={{ marginBottom: 16 }}>
                    {newPasswordResponse.errorDetail ||
                        'Could not complete your password reset request. Please try again.'}
                </ErrorMessage>
            )}
            <Form
                layout="vertical"
                form={form}
                onFinish={(values) => updatePassword(values)}
                requiredMark={false}
                noValidate
            >
                <PasswordInput
                    disabled={newPasswordResponseLoading}
                    showStrengthIndicator
                    validateMinLength
                    help={
                        <span style={{ display: 'flex', alignItems: 'center' }}>
                            <ExclamationCircleFilled style={{ marginRight: 4 }} />
                            Passwords must be at least 8 characters
                        </span>
                    }
                />
                <PasswordInput
                    disabled={newPasswordResponseLoading}
                    validationDisabled
                    label="Confirm new password"
                    name="passwordConfirm"
                />
                <Form.Item>
                    <Button
                        className="btn-bridge"
                        htmlType="submit"
                        data-attr="password-reset-complete"
                        loading={newPasswordResponseLoading}
                        block
                    >
                        Change my password
                    </Button>
                </Form.Item>
            </Form>
        </>
    )
}

function ResetInvalid(): JSX.Element {
    const { push } = useActions(router)
    return (
        <div className="text-center">
            The provided link is <b>invalid or has expired</b>. Please request a new link.
            <div className="mt">
                <Button className="btn-bridge" data-attr="back-to-login" block onClick={() => push('/reset')}>
                    Request new link
                </Button>
            </div>
        </div>
    )
}
