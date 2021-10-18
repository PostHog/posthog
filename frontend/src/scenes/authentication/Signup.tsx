import { Col, Row, Form, Input, Button } from 'antd'
import React, { useEffect, useRef } from 'react'
import './Signup.scss'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PasswordInput } from './PasswordInput'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { signupLogic } from './signupLogic'
import { Rule } from 'rc-field-form/lib/interface'
import { ExclamationCircleFilled } from '@ant-design/icons'
import { userLogic } from '../userLogic'
import { WelcomeLogo } from './WelcomeLogo'
import hedgehogMain from 'public/hedgehog-bridge-page.png'
import { ErrorMessage } from 'lib/components/ErrorMessage/ErrorMessage'

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=signup-header'

const requiredRule = (message: string): Rule[] | undefined => {
    return [
        {
            required: true,
            message: (
                <>
                    <ExclamationCircleFilled style={{ marginLeft: 4 }} /> {message}
                </>
            ),
        },
    ]
}

export function Signup(): JSX.Element | null {
    const [form] = Form.useForm()
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { signupResponse, signupResponseLoading, initialEmail, formSubmitted } = useValues(signupLogic)
    const { signup, setFormSubmitted } = useActions(signupLogic)
    const emailInputRef = useRef<Input | null>(null)
    const passwordInputRef = useRef<Input | null>(null)

    useEffect(() => {
        if (initialEmail) {
            passwordInputRef?.current?.focus()
        } else {
            emailInputRef?.current?.focus()
        }
    }, [initialEmail])

    const handleFormSubmit = async (values: Record<string, string>): Promise<void> => {
        setFormSubmitted(true)
        if (await form.validateFields(['email', 'password', 'first_name', 'organization_name'])) {
            signup(values)
        }
    }

    const footerHighlights = {
        cloud: ['Hosted & managed by PostHog', 'Pay per event, cancel anytime', 'Community, Slack & email support'],
        selfHosted: [
            'Fully featured product, unlimited events',
            'Data in your own infrastructure',
            'Community, Slack & email support',
        ],
    }

    return !user ? (
        <div className="bridge-page signup">
            <Row>
                <Col span={24} className="auth-main-content">
                    <img src={hedgehogMain} alt="" className="main-art" />
                    <div className="inner-wrapper">
                        <WelcomeLogo view="signup" />
                        <div className="inner">
                            <h2 className="subtitle" style={{ justifyContent: 'center' }}>
                                Get started
                            </h2>
                            {(preflight?.cloud || preflight?.initiated) && ( // For now, if you're not on Cloud, you wouldn't see
                                // this page, but future-proofing this (with `preflight.initiated`) in case this changes.
                                <div className="text-center" style={{ marginBottom: 32 }}>
                                    Already have an account?{' '}
                                    <Link to="/login" data-attr="signup-login-link">
                                        Log in
                                    </Link>
                                </div>
                            )}
                            {!signupResponseLoading &&
                                signupResponse?.errorCode &&
                                !['email', 'password'].includes(signupResponse?.errorAttribute || '') && (
                                    <ErrorMessage style={{ marginBottom: 16 }}>
                                        {signupResponse?.errorDetail ||
                                            'Could not complete your signup. Please try again.'}
                                    </ErrorMessage>
                                )}
                            <Form
                                layout="vertical"
                                form={form}
                                onFinish={handleFormSubmit}
                                requiredMark={false}
                                initialValues={{ email: initialEmail }}
                                noValidate
                            >
                                <Form.Item
                                    name="email"
                                    label="Email"
                                    rules={
                                        formSubmitted
                                            ? [
                                                  ...(requiredRule('Please enter your email to continue') || []),
                                                  {
                                                      type: 'email',
                                                      message: (
                                                          <>
                                                              <ExclamationCircleFilled style={{ marginLeft: 4 }} />{' '}
                                                              Please enter a valid email
                                                          </>
                                                      ),
                                                  },
                                              ]
                                            : undefined
                                    }
                                    validateStatus={signupResponse?.errorAttribute === 'email' ? 'error' : undefined}
                                    help={
                                        signupResponse?.errorAttribute === 'email'
                                            ? signupResponse.errorDetail
                                            : undefined
                                    }
                                >
                                    <Input
                                        className="ph-ignore-input"
                                        autoFocus
                                        data-attr="signup-email"
                                        placeholder="email@yourcompany.com"
                                        type="email"
                                        ref={emailInputRef}
                                        disabled={signupResponseLoading}
                                    />
                                </Form.Item>
                                <PasswordInput
                                    ref={passwordInputRef}
                                    showStrengthIndicator
                                    validateStatus={signupResponse?.errorAttribute === 'password' ? 'error' : undefined}
                                    help={
                                        signupResponse?.errorAttribute === 'password' ? (
                                            signupResponse.errorDetail
                                        ) : (
                                            <span style={{ paddingBottom: 16 }}>
                                                <ExclamationCircleFilled style={{ marginRight: 4 }} />
                                                Passwords must be at least 8 characters
                                            </span>
                                        )
                                    }
                                    validateMinLength
                                    validationDisabled={!formSubmitted}
                                    disabled={signupResponseLoading}
                                />
                                <Form.Item
                                    name="first_name"
                                    label="Your full name"
                                    rules={formSubmitted ? requiredRule('Please enter your first name') : undefined}
                                >
                                    <Input
                                        className="ph-ignore-input"
                                        autoFocus
                                        data-attr="signup-first-name"
                                        placeholder="Jane Doe"
                                        disabled={signupResponseLoading}
                                    />
                                </Form.Item>
                                <Form.Item
                                    name="organization_name"
                                    label="Organization name"
                                    rules={
                                        formSubmitted
                                            ? requiredRule('Please enter the name of your organization')
                                            : undefined
                                    }
                                >
                                    <Input
                                        className="ph-ignore-input"
                                        data-attr="signup-organization-name"
                                        placeholder="Hogflix Movies"
                                        disabled={signupResponseLoading}
                                    />
                                </Form.Item>

                                <Form.Item className="text-center" style={{ marginTop: 32 }}>
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
                                        className="btn-bridge"
                                        htmlType="submit"
                                        data-attr="signup-submit"
                                        block
                                        loading={signupResponseLoading}
                                    >
                                        Create account
                                    </Button>
                                </Form.Item>
                            </Form>
                            <div>
                                <SocialLoginButtons caption="Or sign up with" />
                            </div>
                        </div>
                    </div>
                </Col>
            </Row>
            <footer>
                <div className="footer-inner">
                    {footerHighlights[preflight?.cloud ? 'cloud' : 'selfHosted'].map((val, idx) => (
                        <span key={idx}>{val}</span>
                    ))}
                </div>
            </footer>
        </div>
    ) : null
}
