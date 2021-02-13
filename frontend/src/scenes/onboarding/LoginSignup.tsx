import { Button, Col, Input, Row } from 'antd'
import React, { lazy, Suspense, useState } from 'react'
import './LoginSignup.scss'
import smLogo from 'public/icon-white.svg'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { PrevalidatedInvite } from '~/types'

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

    return (
        <div className="login-signup">
            <Row>
                <Col span={10} className="image-showcase">
                    <div className="the-mountains" />
                    <div className="main-logo">
                        <img src={smLogo} alt="" />
                    </div>
                    <div className="showcase-content">
                        <h1 className="page-title">Join {invite?.organization_name || 'us'} at PostHog</h1>
                        <div className="showcase-caption">{showcaseCaption}</div>
                    </div>
                </Col>
                <Col span={14} className="rhs-content">
                    <div className="rhs-inner">
                        <SocialLoginButtons queryString={invite ? `?invite_id=${invite.id}` : ''} />
                        <div className="password-login">
                            <form>
                                <div className="input-set">
                                    <label htmlFor="first_name">First Name</label>
                                    <Input
                                        placeholder="Jane"
                                        type="text"
                                        autoFocus
                                        required
                                        disabled={false}
                                        id="first_name"
                                    />
                                </div>
                                <div className="input-set">
                                    <label htmlFor="password">Password</label>
                                    <Input
                                        placeholder="*******"
                                        type="password"
                                        required
                                        disabled={false}
                                        value={formState.password}
                                        onChange={(e) => setFormState({ ...formState, password: e.target.value })}
                                        id="password"
                                    />
                                    <Suspense fallback={<></>}>
                                        <PasswordStrength password={formState.password} />
                                    </Suspense>
                                </div>
                            </form>
                            <Button
                                type="primary"
                                htmlType="submit"
                                data-attr="password-signup"
                                disabled={false}
                                loading={false}
                                block
                            >
                                Create my account
                            </Button>
                        </div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}
