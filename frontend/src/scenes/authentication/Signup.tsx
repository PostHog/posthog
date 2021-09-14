import { Col, Row, Form, Input, Button, Alert, Grid } from 'antd'
import React, { useEffect, useRef } from 'react'
import logo from 'public/posthog-logo-white.svg'
import './Signup.scss'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PasswordInput } from './PasswordInput'
import { IconRocket } from 'lib/components/icons'
import { Breakpoint } from 'antd/lib/_util/responsiveObserve'
import { SignupSideContentCloud, SignupSideContentHosted } from './SignupSideContent'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { signupLogic } from './signupLogic'
import { Rule } from 'rc-field-form/lib/interface'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { userLogic } from '../userLogic'

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=signup-header'

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
                    {
                        required: true,
                        message: 'Please enter your email to continue',
                    },
                ]}
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
                label="Create a password"
                showStrengthIndicator
                validateStatus={signupResponse?.errorAttribute === 'password' ? 'error' : undefined}
                help={signupResponse?.errorAttribute === 'password' ? signupResponse.errorDetail : undefined}
                validateMinLength
            />
            <Form.Item>
                <Button className="rocket-button" htmlType="submit" data-attr="signup-continue" block>
                    <span className="icon">
                        <IconRocket />
                    </span>
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

    useEffect(() => {
        if (formStep === 2) {
            firstNameInputRef?.current?.focus()
        }
    }, [formStep])

    const requiredRule = (message: string): Rule[] | undefined => {
        // Required rule only enabled when the user is in the current step to allow the user to freely move between steps
        if (formStep !== 2) {
            return undefined
        }
        return [
            {
                required: true,
                message,
            },
        ]
    }

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
            <Form.Item name="first_name" label="Your full name" rules={requiredRule('Please enter your first name')}>
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
                rules={requiredRule('Please enter the name of your organization')}
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
                    className="rocket-button"
                    htmlType="submit"
                    data-attr="signup-submit"
                    block
                    loading={signupResponseLoading}
                >
                    <span className="icon">
                        <IconRocket />
                    </span>
                    Create account
                </Button>
            </Form.Item>
        </div>
    )
}

export function Signup(): JSX.Element | null {
    const [form] = Form.useForm()
    const { useBreakpoint } = Grid
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { formStep, signupResponse, signupResponseLoading, initialEmail } = useValues(signupLogic)
    const { setFormStep, signup } = useActions(signupLogic)
    const screens = useBreakpoint()
    const isSmallScreen = (Object.keys(screens) as Breakpoint[]).filter((key) => screens[key]).length <= 2 // xs; sm

    const handleFormSubmit = (values: Record<string, string>): void => {
        if (formStep === 1) {
            setFormStep(2)
        } else {
            signup(values)
        }
    }

    return !user ? (
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
                        {(preflight?.cloud || preflight?.initiated) && ( // For now, if you're not on Cloud, you wouldn't see
                            // this page, but future-proofing this (with `preflight.initiated`) in case this changes.
                            <div className="text-center" style={{ marginBottom: 32 }}>
                                Already have an account?{' '}
                                <Link to="/login" data-attr="signup-login-link">
                                    Sign in
                                </Link>
                            </div>
                        )}
                        {!signupResponseLoading &&
                            signupResponse?.errorCode &&
                            !['email', 'password'].includes(signupResponse?.errorAttribute || '') && (
                                <Alert
                                    message="Could not complete your signup. Please try again."
                                    description={signupResponse?.errorDetail}
                                    type="error"
                                    showIcon
                                    style={{ marginBottom: 16 }}
                                />
                            )}
                        <Form
                            layout="vertical"
                            form={form}
                            onFinish={handleFormSubmit}
                            requiredMark={false}
                            initialValues={{ email: initialEmail }}
                        >
                            <FormStepOne />
                            <FormStepTwo />
                        </Form>
                        <div style={{ marginTop: 48 }}>
                            <SocialLoginButtons displayStyle="link" caption="Or sign up with:" />
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    ) : null
}
