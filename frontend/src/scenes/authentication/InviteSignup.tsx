import { useActions, useValues } from 'kea'
import React, { lazy, Suspense, useRef, useState } from 'react'
import { inviteSignupLogic, ErrorCodes } from './inviteSignupLogic'
import { SceneLoading } from 'lib/utils'
import './InviteSignup.scss'
import { StarryBackground } from 'lib/components/StarryBackground'
import { userLogic } from 'scenes/userLogic'
import { Button, Row, Col, Input, Space } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, ArrowDownOutlined } from '@ant-design/icons'
import { router } from 'kea-router'
import { PrevalidatedInvite, UserType } from '~/types'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import smLogo from 'public/icon-white.svg'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { ProfilePicture } from '../../lib/components/ProfilePicture'

export const scene: SceneExport = {
    component: InviteSignup,
    logic: inviteSignupLogic,
}

export function WhoAmI({ user }: { user: UserType }): JSX.Element {
    return (
        <div className="whoami cursor-pointer" data-attr="top-navigation-whoami">
            <ProfilePicture name={user.first_name} email={user.email} />
            <div className="details hide-lte-lg">
                <span>{user.first_name}</span>
                <span>{user.organization?.name}</span>
            </div>
        </div>
    )
}

const UTM_TAGS = 'utm_medium=in-product&utm_campaign=invite-signup'
const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

interface ErrorMessage {
    title: string
    detail: JSX.Element | string
    actions: JSX.Element
}

function HelperLinks(): JSX.Element {
    return (
        <>
            <a className="plain-link" href="/">
                App Home
            </a>
            <a
                className="plain-link"
                href={`https://posthog.com?${UTM_TAGS}&utm_message=invalid-invite`}
                rel="noopener"
            >
                PostHog Website
            </a>
            <a
                className="plain-link"
                href={`https://posthog.com/slack?${UTM_TAGS}&utm_message=invalid-invite`}
                rel="noopener"
            >
                Contact Us
            </a>
        </>
    )
}

function BackToPostHog(): JSX.Element {
    const { push } = useActions(router)
    return (
        <Button icon={<ArrowLeftOutlined />} block onClick={() => push(urls.default())}>
            Go back to PostHog
        </Button>
    )
}

function ErrorView(): JSX.Element | null {
    const { error } = useValues(inviteSignupLogic)
    const { user } = useValues(userLogic)

    const ErrorMessages: Record<ErrorCodes, ErrorMessage> = {
        [ErrorCodes.InvalidInvite]: {
            title: 'Oops! This invite link is invalid or has expired',
            detail: (
                <>
                    {error?.detail} If you believe this is a mistake, please contact whoever created this invite and{' '}
                    <b>ask them for a new invite</b>.
                </>
            ),
            actions: user ? <BackToPostHog /> : <HelperLinks />,
        },
        [ErrorCodes.InvalidRecipient]: {
            title: 'Oops! You cannot use this invite link',
            detail: (
                <>
                    <div>{error?.detail}</div>
                    <div className="mt">
                        {user ? (
                            <span>
                                You can either log out and create a new account under the new email address or ask the
                                organization admin to send a{' '}
                                <b>new invite to the email address on your account, {user?.email}</b>.
                            </span>
                        ) : (
                            <div>
                                You need to log in with the email address above, or create your own password.
                                <div className="mt">
                                    <Button icon={<ArrowLeftOutlined />} href={window.location.pathname}>
                                        Try again
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                </>
            ),
            actions: user ? <BackToPostHog /> : <HelperLinks />,
        },
        [ErrorCodes.Unknown]: {
            title: 'Oops! We could not validate this invite link',
            detail: `${error?.detail} There was an issue with your invite link, please try again in a few seconds. If the problem persists, contact us.`,
            actions: user ? <BackToPostHog /> : <HelperLinks />,
        },
    }

    if (!error) {
        return null
    }

    return (
        <StarryBackground>
            <div className="error-view-container">
                <div className="inner">
                    <h1 className="page-title">{ErrorMessages[error.code].title}</h1>
                    <div className="error-message">{ErrorMessages[error.code].detail}</div>
                    <div className="actions">{ErrorMessages[error.code].actions}</div>
                </div>
            </div>
        </StarryBackground>
    )
}

function AuthenticatedAcceptInvite({ invite }: { invite: PrevalidatedInvite }): JSX.Element {
    const { user } = useValues(userLogic)
    const { acceptInvite } = useActions(inviteSignupLogic)
    const { acceptedInviteLoading, acceptedInvite } = useValues(inviteSignupLogic)

    return (
        <div className="authenticated-invite">
            <Space className="inner" direction="vertical" align="center">
                <Row>
                    <h1 className="page-title">You have been invited to join {invite.organization_name}</h1>
                </Row>
                <Row>
                    <span>
                        You will accept the invite under your <b>existing PostHog account</b> ({user?.email})
                    </span>
                </Row>
                {user && (
                    <Row>
                        <div className="whoami-mock">
                            <div className="whoami-inner-container">
                                <WhoAmI user={user} />
                            </div>
                        </div>
                    </Row>
                )}
                <Row>
                    You can change organizations at any time by clicking on the dropdown at the top right corner of the
                    navigation bar.
                </Row>
                <div>
                    {!acceptedInvite ? (
                        <>
                            <Button
                                type="primary"
                                block
                                onClick={() => acceptInvite()}
                                disabled={acceptedInviteLoading}
                            >
                                Accept invite
                            </Button>
                            <div className="mt">
                                <Link to="/">
                                    <ArrowLeftOutlined /> Go back to PostHog
                                </Link>
                            </div>
                        </>
                    ) : (
                        <Button block onClick={() => (window.location.href = '/')}>
                            Go to PostHog <ArrowRightOutlined />
                        </Button>
                    )}
                </div>
            </Space>
        </div>
    )
}

function UnauthenticatedAcceptInvite({ invite }: { invite: PrevalidatedInvite }): JSX.Element {
    const [formValues, setFormValues] = useState({
        firstName: invite?.first_name || '',
        password: '',
        emailOptIn: true,
    })
    const [formState, setFormState] = useState({ submitted: false, passwordInvalid: false })
    const passwordInputRef = useRef<Input | null>(null)
    const { acceptInvite } = useActions(inviteSignupLogic)
    const { acceptedInviteLoading } = useValues(inviteSignupLogic)
    const { socialAuthAvailable } = useValues(preflightLogic)

    const parentContainerRef = useRef<HTMLDivElement | null>(null) // Used for scrolling on mobile
    const mainContainerRef = useRef<HTMLDivElement | null>(null) // Used for scrolling on mobile

    const goToMainContent = (): void => {
        const yPos = mainContainerRef.current ? mainContainerRef.current.getBoundingClientRect().top : null
        if (yPos) {
            parentContainerRef.current?.scrollTo(0, yPos)
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
        <div className="unauthenticated-invite" ref={parentContainerRef}>
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
                                <Button icon={<ArrowDownOutlined />} type="default" onClick={goToMainContent}>
                                    Continue
                                </Button>
                            </div>
                        </div>
                    </div>
                </Col>
                <Col span={24} md={14} className="rhs-content" ref={mainContainerRef}>
                    <div className="rhs-inner">
                        <SocialLoginButtons
                            title="Continue with a provider"
                            caption={`Remember to log in with ${invite?.target_email}`}
                            queryString={invite ? `?invite_id=${invite.id}` : ''}
                        />
                        <div className="password-login">
                            <h3 className="l3 text-center">
                                {socialAuthAvailable ? 'Or create your own password' : 'Create your PostHog account'}
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
                                        style={{ fontSize: 12, color: 'var(--muted)' }}
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

export function InviteSignup(): JSX.Element {
    const { invite, inviteLoading } = useValues(inviteSignupLogic)
    const { user } = useValues(userLogic)

    if (inviteLoading) {
        return <SceneLoading />
    }

    return (
        <div className={`invite-signup${user ? ' authenticated' : ''}`}>
            <ErrorView />
            {invite &&
                (user ? (
                    <AuthenticatedAcceptInvite invite={invite} />
                ) : (
                    <UnauthenticatedAcceptInvite invite={invite} />
                ))}
        </div>
    )
}
