import { Button, Col, Input, Row } from 'antd'
import React, { lazy, Suspense, useRef, useState } from 'react'
import './LoginSignup.scss'
import smLogo from 'public/icon-white.svg'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PrevalidatedInvite } from '~/types'
import { Link } from 'lib/components/Link'
import { ArrowDownOutlined } from '@ant-design/icons'

const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

interface LoginSignupProps {
    showcaseCaption?: JSX.Element | string
    invite?: PrevalidatedInvite | null
}

export function LoginSignup({ showcaseCaption, invite }: LoginSignupProps): JSX.Element {
    /*
    UI component for the login & signup pages.
    Currently used for: InviteSignup.
    */
    const [formState, setFormState] = useState({ firstName: '', password: '' })
    const mainContainerRef = useRef<HTMLDivElement | null>(null)
    const rhsContainerRef = useRef<HTMLDivElement | null>(null)

    const handleScroll = (): void => {
        const yPos = rhsContainerRef.current ? rhsContainerRef.current.getBoundingClientRect().top : null
        if (yPos) {
            mainContainerRef.current?.scrollTo(0, yPos)
        }
    }

    return (
        <div className="login-signup" ref={mainContainerRef}>
            <Row>
                <Col span={24} md={10} className="image-showcase">
                    <div className="the-mountains" />
                    <div className="main-logo">
                        <img src={smLogo} alt="" />
                    </div>
                    <div className="showcase-content">
                        <h1 className="page-title">
                            Join <b>{invite?.organization_name || 'us'}</b> at
                        </h1>
                        <div className="wordmark">PostHog</div>
                        <div className="showcase-caption">{showcaseCaption}</div>
                        <div className="mobile-continue">
                            <Button icon={<ArrowDownOutlined />} type="default" onClick={handleScroll}>
                                Continue
                            </Button>
                        </div>
                    </div>
                </Col>
                <Col span={24} md={14} className="rhs-content" ref={rhsContainerRef}>
                    <div className="top-helper" style={{ marginRight: 32 }}>
                        <b>Already have an account?</b>{' '}
                        <Link to="/login?utm_message=login-to-accept-invite">Log in to accept your invite</Link>
                    </div>
                    <div className="rhs-inner">
                        <SocialLoginButtons
                            title="Create your account with a provider"
                            caption="One less password to manage"
                            queryString={invite ? `?invite_id=${invite.id}` : ''}
                        />
                        <div className="password-login">
                            <h3 className="l3 text-center">Or create your own password</h3>
                            <form>
                                <div className="input-set">
                                    <label htmlFor="email">Email</label>
                                    <Input type="email" disabled id="email" value={invite?.target_email} />
                                </div>
                                <div className="input-set">
                                    <label htmlFor="password">Password</label>
                                    <Input
                                        placeholder="*******"
                                        type="password"
                                        required
                                        disabled={false}
                                        autoFocus={window.screen.width >= 768} // do not autofocus on small-width screens
                                        value={formState.password}
                                        onChange={(e) => setFormState({ ...formState, password: e.target.value })}
                                        id="password"
                                    />
                                    <span className="caption">Your password must have at least 8 characters.</span>
                                    <Suspense fallback={<></>}>
                                        <PasswordStrength password={formState.password} />
                                    </Suspense>
                                </div>
                                <div className="input-set">
                                    <label htmlFor="first_name">First Name</label>
                                    <Input
                                        placeholder="Jane"
                                        type="text"
                                        required
                                        disabled={false}
                                        id="first_name"
                                        defaultValue={invite?.first_name}
                                    />
                                    {invite?.first_name && (
                                        <span className="caption">
                                            Your name was provided in the invite, feel free to change it.
                                        </span>
                                    )}
                                </div>
                                <Button
                                    type="primary"
                                    htmlType="submit"
                                    data-attr="password-signup"
                                    disabled={false}
                                    loading={false}
                                    block
                                >
                                    Continue
                                </Button>
                            </form>
                            <div className="mt text-center text-muted">
                                Already have an account? <Link to="/login">Log in</Link>
                            </div>
                            <div className="mt text-center" style={{ marginBottom: 60 }}>
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
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}
