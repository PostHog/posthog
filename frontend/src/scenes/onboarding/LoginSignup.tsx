import { Button, Col, Input, Row } from 'antd'
import React, { lazy, Suspense, useRef, useState } from 'react'
import './LoginSignup.scss'
import smLogo from 'public/icon-white.svg'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PrevalidatedInvite } from '~/types'
import { Link } from 'lib/components/Link'
import { ArrowDownOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { inviteSignupLogic } from './inviteSignupLogic'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

interface LoginSignupProps {
    invite?: PrevalidatedInvite | null
}

export function LoginSignup({ invite }: LoginSignupProps): JSX.Element {
    /*
    UI component for the login & signup pages.
    Currently used for: InviteSignup.
    */
    const [formValues, setFormValues] = useState({
        firstName: invite?.first_name || '',
        password: '',
        emailOptIn: true,
    })
    const [formState, setFormState] = useState({ submitted: false, passwordInvalid: false })
    const mainContainerRef = useRef<HTMLDivElement | null>(null)
    const rhsContainerRef = useRef<HTMLDivElement | null>(null)
    const passwordInputRef = useRef<Input | null>(null)
    const { acceptInvite } = useActions(inviteSignupLogic)
    const { acceptedInviteLoading } = useValues(inviteSignupLogic)
    const { socialAuthAvailable } = useValues(preflightLogic)

    const handleScroll = (): void => {
        const yPos = rhsContainerRef.current ? rhsContainerRef.current.getBoundingClientRect().top : null
        if (yPos) {
            mainContainerRef.current?.scrollTo(0, yPos)
        }
    }

    const handlePasswordChanged = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const { value } = e.target
        setFormValues({ ...formValues, password: value })
        if (value.length >= 8) {
            setFormState({ ...formState, passwordInvalid: false })
        } else {
            setFormState({ ...formState, passwordInvalid: true })
        }
    }

    const handleFormSubmit = (e: React.FormEvent<EventTarget>): void => {
        e.preventDefault()
        if (formState.passwordInvalid) {
            setFormState({ ...formState, submitted: true })
            if (passwordInputRef.current) {
                passwordInputRef.current.focus()
            }
            return
        }

        const payload = {
            first_name: formValues.firstName,
            password: formValues.password,
            email_opt_in: formValues.emailOptIn,
        }
        acceptInvite(payload)
    }

    return (
        <div className="login-signup" ref={mainContainerRef}>
            <Row>
                <Col span={24} md={10} className="image-showcase-container">
                    <div className="image-showcase ant-col-24 ant-col-md-10">
                        <div className="the-mountains" />
                        <div className="main-logo">
                            <img src={smLogo} alt="" />
                        </div>
                        <div className="showcase-content">
                            <h1 className="page-title">
                                Hello{invite?.first_name ? ` ${invite.first_name}` : ''}! You've been invited to join
                            </h1>
                            <div className="company">{invite?.organization_name || 'us'}</div>
                            <h1 className="page-title">on PostHog</h1>
                            <div className="mobile-continue">
                                <Button icon={<ArrowDownOutlined />} type="default" onClick={handleScroll}>
                                    Continue
                                </Button>
                            </div>
                        </div>
                    </div>
                </Col>
                <Col span={24} md={14} className="rhs-content" ref={rhsContainerRef}>
                    <div className="rhs-inner">
                        <SocialLoginButtons
                            title="Continue with a provider"
                            caption={`Remember to log in with ${invite?.target_email}`}
                            queryString={invite ? `?invite_id=${invite.id}` : ''}
                        />
                        <div className="password-login">
                            <h3 className="l3 text-center">
                                {socialAuthAvailable ? 'Or create your own passowrd' : 'Create your PostHog account'}
                            </h3>
                            <form onSubmit={handleFormSubmit}>
                                <div className="input-set">
                                    <label htmlFor="email">Email</label>
                                    <Input type="email" disabled id="email" value={invite?.target_email} />
                                </div>
                                <div
                                    className={`input-set${
                                        formState.submitted && formState.passwordInvalid ? ' errored' : ''
                                    }`}
                                    style={{ paddingBottom: 8 }}
                                >
                                    <label htmlFor="password">Password</label>
                                    <Input
                                        placeholder="*******"
                                        type="password"
                                        required
                                        disabled={acceptedInviteLoading}
                                        autoFocus={window.screen.width >= 768} // do not autofocus on small-width screens
                                        value={formValues.password}
                                        onChange={handlePasswordChanged}
                                        id="password"
                                        ref={passwordInputRef}
                                    />
                                    <span className="caption">Your password must have at least 8 characters.</span>
                                    <Suspense fallback={<></>}>
                                        <PasswordStrength password={formValues.password} />
                                    </Suspense>
                                </div>
                                <div className="input-set">
                                    <label htmlFor="first_name">First Name</label>
                                    <Input
                                        placeholder="Jane"
                                        type="text"
                                        required
                                        disabled={acceptedInviteLoading}
                                        id="first_name"
                                        value={formValues.firstName}
                                        onChange={(e) => setFormValues({ ...formValues, firstName: e.target.value })}
                                    />
                                    {invite?.first_name && (
                                        <span className="caption">
                                            Your name was provided in the invite, feel free to change it.
                                        </span>
                                    )}
                                </div>
                                <div className="mb">
                                    <Checkbox
                                        checked={formValues.emailOptIn}
                                        onChange={(e) => setFormValues({ ...formValues, emailOptIn: e.target.checked })}
                                        disabled={acceptedInviteLoading}
                                        style={{ fontSize: 12, color: 'var(--text-muted)' }}
                                    >
                                        Send me product and security updates
                                    </Checkbox>
                                </div>
                                <Button
                                    type="primary"
                                    htmlType="submit"
                                    data-attr="password-signup"
                                    disabled={formState.submitted && formState.passwordInvalid}
                                    loading={acceptedInviteLoading}
                                    block
                                >
                                    Continue
                                </Button>
                            </form>
                            <div className="mt text-center">
                                By clicking continue you agree to our{' '}
                                <a href="https://posthog.com/terms" target="_blank" rel="noopener">
                                    Terms of Service
                                </a>{' '}
                                and{' '}
                                <a href="https://posthog.com/privacy" target="_blank" rel="noopener">
                                    Privacy Policy
                                </a>
                                .
                            </div>
                            <div className="mt text-center text-muted" style={{ marginBottom: 60 }}>
                                Already have an account? <Link to="/login">Log in</Link>
                            </div>
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}
