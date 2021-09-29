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
import { ArrowLeftOutlined, ExclamationCircleFilled } from '@ant-design/icons'
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

function FormStepOne(): JSX.Element {
    const { formStep, signupResponse, initialEmail } = useValues(signupLogic)
    const emailInputRef = useRef<Input | null>(null)
    const passwordInputRef = useRef<Input | null>(null)

    useEffect(() => {
        if (formStep === 1) {
            if (initialEmail) {
                passwordInputRef?.current?.focus()
            } else {
                emailInputRef?.current?.focus()
            }
        }
    }, [formStep, initialEmail])

    return (
        <div className={`form-step form-step-one${formStep !== 1 ? ' hide' : ''}`}>
            <Form.Item
                name="email"
                label="Email"
                rules={[
                    ...(requiredRule('Please enter your email to continue') || []),
                    {
                        type: 'email',
                        message: (
                            <>
                                <ExclamationCircleFilled style={{ marginLeft: 4 }} /> Please input a valid email
                            </>
                        ),
                    },
                ]}
                validateTrigger={['onSubmit']}
                validateStatus={signupResponse?.errorAttribute === 'email' ? 'error' : undefined}
                help={signupResponse?.errorAttribute === 'email' ? signupResponse.errorDetail : undefined}
            >
                <Input
                    className="ph-ignore-input"
                    autoFocus
                    data-attr="signup-email"
                    placeholder="email@yourcompany.com"
                    type="email"
                    ref={emailInputRef}
                />
            </Form.Item>
            <PasswordInput
                ref={passwordInputRef}
                showStrengthIndicator
                validateStatus={signupResponse?.errorAttribute === 'password' ? 'error' : undefined}
                help={signupResponse?.errorAttribute === 'password' ? signupResponse.errorDetail : undefined}
                validateMinLength
            />
            <Form.Item>
                <Button className="btn-bridge" htmlType="submit" data-attr="signup-continue" block>
                    Continue
                </Button>
            </Form.Item>
        </div>
    )
}

function FormStepTwo(): JSX.Element {
    const { formStep, signupResponseLoading } = useValues(signupLogic)
    const { setFormStep } = useActions(signupLogic)

    const firstNameInputRef = useRef<Input | null>(null)

    const wrappedRequireRule = (message: string): Rule[] | undefined => {
        // Required rule only enabled when the user is in the current step to allow the user to freely move between steps
        if (formStep !== 2) {
            return undefined
        }
        return requiredRule(message)
    }

    useEffect(() => {
        if (formStep === 2) {
            firstNameInputRef?.current?.focus()
        }
    }, [formStep])

    return (
        <div className={`form-step${formStep !== 2 ? ' hide' : ''}`}>
            <div className="mb">
                <Button
                    type="link"
                    onClick={() => setFormStep(1)}
                    icon={<ArrowLeftOutlined />}
                    disabled={signupResponseLoading}
                >
                    Go back
                </Button>
            </div>
            <div className="mb">
                <b>Just a few more details ...</b>
            </div>
            <Form.Item
                name="first_name"
                label="Your full name"
                rules={wrappedRequireRule('Please enter your first name')}
            >
                <Input
                    className="ph-ignore-input"
                    autoFocus
                    data-attr="signup-first-name"
                    placeholder="Jane Doe"
                    ref={firstNameInputRef}
                    disabled={signupResponseLoading}
                />
            </Form.Item>
            <Form.Item
                name="organization_name"
                label="Organization name"
                rules={wrappedRequireRule('Please enter the name of your organization')}
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
        </div>
    )
}

export function Signup(): JSX.Element | null {
    const [form] = Form.useForm()
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { formStep, signupResponse, signupResponseLoading, initialEmail } = useValues(signupLogic)
    const { setFormStep, signup } = useActions(signupLogic)

    const handleFormSubmit = (values: Record<string, string>): void => {
        if (formStep === 1) {
            setFormStep(2)
        } else {
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
                                <FormStepOne />
                                <FormStepTwo />
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
