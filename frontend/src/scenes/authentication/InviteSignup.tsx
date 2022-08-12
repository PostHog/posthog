import { useActions, useValues } from 'kea'
import React, { useRef } from 'react'
import { inviteSignupLogic, ErrorCodes } from './inviteSignupLogic'
import { Loading } from 'lib/utils'
import './InviteSignup.scss'
import { StarryBackground } from 'lib/components/StarryBackground'
import { userLogic } from 'scenes/userLogic'
import { PrevalidatedInvite, UserType } from '~/types'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import smLogo from 'public/icon-white.svg'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { ProfilePicture } from '../../lib/components/ProfilePicture'
import { IconArrowDropDown, IconChevronLeft, IconChevronRight } from 'lib/components/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field, PureField } from 'lib/forms/Field'
import PasswordStrength from 'lib/components/PasswordStrength'
import clsx from 'clsx'

export const scene: SceneExport = {
    component: InviteSignup,
    logic: inviteSignupLogic,
}

export function WhoAmI({ user }: { user: UserType }): JSX.Element {
    return (
        <div className="whoami cursor-pointer" data-attr="top-navigation-whoami">
            <ProfilePicture name={user.first_name} email={user.email} />
            <div className="details">
                <span>{user.first_name}</span>
                <span>{user.organization?.name}</span>
            </div>
        </div>
    )
}

const UTM_TAGS = 'utm_medium=in-product&utm_campaign=invite-signup'

interface ErrorMessage {
    title: string
    detail: JSX.Element | string
    actions: JSX.Element
}

function HelperLinks(): JSX.Element {
    return (
        <span className="text-light font-bold">
            <a className="plain-link" href="/">
                App Home
            </a>
            <span className="mx-2">|</span>
            <a
                className="plain-link"
                href={`https://posthog.com?${UTM_TAGS}&utm_message=invalid-invite`}
                rel="noopener"
            >
                PostHog Website
            </a>
            <span className="mx-2">|</span>
            <a
                className="plain-link"
                href={`https://posthog.com/slack?${UTM_TAGS}&utm_message=invalid-invite`}
                rel="noopener"
            >
                Contact Us
            </a>
        </span>
    )
}

function BackToPostHog(): JSX.Element {
    return (
        <LemonButton type="secondary" icon={<IconChevronLeft />} center fullWidth to={urls.default()}>
            Go back to PostHog
        </LemonButton>
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
                    <div className="mt-4">
                        {user ? (
                            <span>
                                You can either log out and create a new account under the new email address or ask the
                                organization admin to send a{' '}
                                <b>new invite to the email address on your account, {user?.email}</b>.
                            </span>
                        ) : (
                            <div>
                                You need to log in with the email address above, or create your own password.
                                <div className="mt-4">
                                    <LemonButton icon={<IconChevronLeft />} href={window.location.pathname}>
                                        Try again
                                    </LemonButton>
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
            <div className="inner flex flex-col text-center space-y-2">
                <h1 className="page-title">You have been invited to join {invite.organization_name}</h1>
                <div>
                    You will accept the invite under your <b>existing PostHog account</b> ({user?.email})
                </div>
                {user && (
                    <div className="whoami-mock">
                        <div className="whoami-inner-container">
                            <WhoAmI user={user} />
                        </div>
                    </div>
                )}
                <div>
                    You can change organizations at any time by clicking on the dropdown at the top right corner of the
                    navigation bar.
                </div>
                <div>
                    {!acceptedInvite ? (
                        <>
                            <LemonButton
                                type="primary"
                                center
                                fullWidth
                                onClick={() => acceptInvite()}
                                loading={acceptedInviteLoading}
                            >
                                Accept invite
                            </LemonButton>
                            <div className="mt-4">
                                <LemonButton type="secondary" center fullWidth icon={<IconChevronLeft />} to="/">
                                    Go back to PostHog
                                </LemonButton>
                            </div>
                        </>
                    ) : (
                        <LemonButton
                            type="secondary"
                            center
                            fullWidth
                            sideIcon={<IconChevronRight />}
                            onClick={() => (window.location.href = '/')}
                        >
                            Go to PostHog
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}

function UnauthenticatedAcceptInvite({ invite }: { invite: PrevalidatedInvite }): JSX.Element {
    const { signup, isSignupSubmitting } = useValues(inviteSignupLogic)
    const { socialAuthAvailable } = useValues(preflightLogic)

    const parentContainerRef = useRef<HTMLDivElement | null>(null) // Used for scrolling on mobile
    const mainContainerRef = useRef<HTMLDivElement | null>(null) // Used for scrolling on mobile

    const goToMainContent = (): void => {
        const yPos = mainContainerRef.current ? mainContainerRef.current.getBoundingClientRect().top : null
        if (yPos) {
            parentContainerRef.current?.scrollTo(0, yPos)
        }
    }
    return (
        <div className="UnauthenticatedInvite" ref={parentContainerRef}>
            <div className="UnauthenticatedInvite__showcase">
                <div className="UnauthenticatedInvite__showcase__mountains" />
                <div className="UnauthenticatedInvite__showcase__mainlogo">
                    <img src={smLogo} alt="" />
                </div>
                <div className="UnauthenticatedInvite__showcase__content">
                    <div className="text-3xl font-semibold flex flex-col gap-2">
                        <span>
                            Hello{invite?.first_name ? ` ${invite.first_name}` : ''}! You've been invited to join
                        </span>
                        <span className="text-4xl font-bold text-white">{invite?.organization_name || 'us'}</span>
                        <span>on PostHog</span>
                    </div>

                    <div className="UnauthenticatedInvite__showcase__continue mt-4">
                        <LemonButton sideIcon={<IconArrowDropDown />} type="secondary" onClick={goToMainContent}>
                            Continue
                        </LemonButton>
                    </div>
                </div>
            </div>
            <div className="UnauthenticatedInvite__content" ref={mainContainerRef}>
                <div className="UnauthenticatedInvite__content__inner">
                    <SocialLoginButtons
                        className="mb-4"
                        title="Continue with a provider"
                        caption={`Remember to log in with ${invite?.target_email}`}
                        queryString={invite ? `?invite_id=${invite.id}` : ''}
                    />
                    <h3 className="text-center">
                        {socialAuthAvailable ? 'Or create your own password' : 'Create your PostHog account'}
                    </h3>
                    <Form logic={inviteSignupLogic} formKey="signup" className="space-y-4" enableFormOnSubmit>
                        <PureField label="Email">
                            <LemonInput type="email" disabled id="email" value={invite?.target_email} />
                        </PureField>
                        <Field
                            name="password"
                            label={
                                <div className="flex flex-1 items-center justify-between">
                                    <span>Password</span>
                                    <span className="w-20">
                                        <PasswordStrength password={signup.password} />
                                    </span>
                                </div>
                            }
                        >
                            <LemonInput
                                type="password"
                                className="ph-ignore-input"
                                data-attr="password"
                                placeholder="••••••••••"
                                autoFocus={window.screen.width >= 768} // do not autofocus on small-width screens
                                id="password"
                                disabled={isSignupSubmitting}
                            />
                        </Field>

                        <Field
                            name="first_name"
                            label="First Name"
                            help={
                                invite?.first_name
                                    ? 'Your name was provided in the invite, feel free to change it.'
                                    : undefined
                            }
                        >
                            <LemonInput placeholder="Jane" id="first_name" />
                        </Field>

                        <Field name="email_opt_in">
                            {({ value, onChange }) => {
                                console.log({ value })
                                return (
                                    <LemonCheckbox
                                        checked={value}
                                        onChange={(e) => onChange(e.target.checked)}
                                        disabled={isSignupSubmitting}
                                        label="Send me product and security updates"
                                    />
                                )
                            }}
                        </Field>

                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            data-attr="password-signup"
                            loading={isSignupSubmitting}
                            center
                            fullWidth
                        >
                            Continue
                        </LemonButton>
                    </Form>
                    <div className="mt-4 text-center text-muted">
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
                    <div className="mt-4 text-center text-muted mb-20">
                        Already have an account? <Link to="/login">Log in</Link>
                    </div>
                </div>
            </div>
        </div>
    )
}

export function InviteSignup(): JSX.Element {
    const { invite, inviteLoading } = useValues(inviteSignupLogic)
    const { user } = useValues(userLogic)

    if (inviteLoading) {
        return <Loading />
    }

    return (
        <div className={clsx('InviteSignup', !!user && 'InviteSignup--authenticated')}>
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
