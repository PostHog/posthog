import { useActions, useValues } from 'kea'
import { inviteSignupLogic, ErrorCodes } from './inviteSignupLogic'
import { userLogic } from 'scenes/userLogic'
import { PrevalidatedInvite } from '~/types'
import { Link } from 'lib/lemon-ui/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field, PureField } from 'lib/forms/Field'
import PasswordStrength from 'lib/components/PasswordStrength'
import clsx from 'clsx'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { SupportModalButton } from './SupportModalButton'

export const scene: SceneExport = {
    component: InviteSignup,
    logic: inviteSignupLogic,
}

const UTM_TAGS = 'utm_medium=in-product&utm_campaign=invite-signup'

interface ErrorMessage {
    title: string
    detail: JSX.Element | string
    actions: JSX.Element
}

function HelperLinks(): JSX.Element {
    return (
        <div className="font-bold text-center">
            <Link to="/">App Home</Link>
            <span className="mx-2">|</span>
            <Link to={`https://posthog.com?${UTM_TAGS}&utm_message=invalid-invite`}>PostHog Website</Link>
        </div>
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
            title: "Oops! This invite link can't be used",
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
                                    <LemonButton
                                        icon={<IconChevronLeft />}
                                        to={window.location.pathname}
                                        disableClientSideRouting
                                    >
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
            detail: `${
                error?.detail || ''
            } There was an issue with your invite link, please try again in a few seconds. If the problem persists, contact us.`,
            actions: user ? <BackToPostHog /> : <HelperLinks />,
        },
    }

    if (!error) {
        return null
    }

    return (
        <BridgePage view="signup-error" hedgehog message="Oops!" footer={<SupportModalButton />}>
            <h2>{ErrorMessages[error.code].title}</h2>
            <div className="error-message">{ErrorMessages[error.code].detail}</div>
            <LemonDivider dashed className="my-4" />
            <div>{ErrorMessages[error.code].actions}</div>
        </BridgePage>
    )
}

function AuthenticatedAcceptInvite({ invite }: { invite: PrevalidatedInvite }): JSX.Element {
    const { user } = useValues(userLogic)
    const { acceptInvite } = useActions(inviteSignupLogic)
    const { acceptedInviteLoading, acceptedInvite } = useValues(inviteSignupLogic)

    return (
        <BridgePage
            view={'accept-invite'}
            hedgehog
            message={user?.first_name ? `Hey ${user?.first_name}!` : 'Hello!'}
            footer={<SupportModalButton name={user?.first_name} email={user?.email} />}
        >
            <div className="space-y-2">
                <h2>You have been invited to join {invite.organization_name}</h2>
                <div>
                    You will accept the invite under your <b>existing PostHog account</b> ({user?.email})
                </div>
                {user && (
                    <div
                        className="border rounded-lg border-dashed flex items-center gap-2 px-2 py-1"
                        data-attr="top-navigation-whoami"
                    >
                        <ProfilePicture name={user.first_name} email={user.email} />
                        <div className="">
                            <div className="font-bold">{user.first_name}</div>
                            <div>{user.organization?.name}</div>
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
                            <div className="mt-2">
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
        </BridgePage>
    )
}

function UnauthenticatedAcceptInvite({ invite }: { invite: PrevalidatedInvite }): JSX.Element {
    const { signup, isSignupSubmitting } = useValues(inviteSignupLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <BridgePage
            view={'invites-signup'}
            hedgehog
            message={
                <>
                    Welcome to
                    <br /> PostHog{preflight?.cloud ? ' Cloud' : ''}!
                </>
            }
            leftContainerContent={
                <div className="mb-8 text-muted">
                    <div className="font-semibold flex flex-col gap-2 text-center items-center text-lg">
                        <span>You've been invited to join</span>
                        <span className="text-4xl font-bold border-b border-dashed pb-2">
                            {invite?.organization_name || 'us'}
                        </span>
                        <span>on PostHog</span>
                    </div>
                </div>
            }
            footer={<SupportModalButton name={invite.first_name} email={invite.target_email} />}
        >
            <h2 className="text-center">Create your PostHog account</h2>
            <Form logic={inviteSignupLogic} formKey="signup" className="space-y-4" enableFormOnSubmit>
                <PureField label="Email">
                    <LemonInput type="email" disabled value={invite?.target_email} />
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
                        autoComplete="new-password"
                        autoFocus={window.screen.width >= 768} // do not autofocus on small-width screens
                        disabled={isSignupSubmitting}
                    />
                </Field>

                <Field
                    name="first_name"
                    label="First Name"
                    help={
                        invite?.first_name ? 'Your name was provided in the invite, feel free to change it.' : undefined
                    }
                >
                    <LemonInput data-attr="first_name" placeholder="Jane" />
                </Field>

                <SignupRoleSelect />

                <Field name="email_opt_in">
                    {({ value, onChange }) => {
                        return (
                            <LemonCheckbox
                                checked={value}
                                onChange={onChange}
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
                Already have an account? <Link to="/login">Log in</Link>
            </div>
            <div className="mt-4 text-center text-muted">
                By clicking continue you agree to our{' '}
                <Link to="https://posthog.com/terms" target="_blank">
                    Terms of Service
                </Link>{' '}
                and{' '}
                <Link to="https://posthog.com/privacy" target="_blank">
                    Privacy Policy
                </Link>
                .
            </div>
            <SocialLoginButtons
                className="mb-4"
                title="Or sign in with"
                caption={`Remember to log in with ${invite?.target_email}`}
                captionLocation="bottom"
                topDivider
                redirectQueryParams={invite ? { invite_id: invite.id } : undefined}
            />
        </BridgePage>
    )
}

export function InviteSignup(): JSX.Element {
    const { invite, inviteLoading } = useValues(inviteSignupLogic)
    const { user } = useValues(userLogic)

    if (inviteLoading) {
        return <SpinnerOverlay sceneLevel />
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
