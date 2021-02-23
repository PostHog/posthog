import { useActions, useValues } from 'kea'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { inviteSignupLogic, ErrorCodes } from './inviteSignupLogic'
import { SceneLoading } from 'lib/utils'
import './InviteSignup.scss'
import { StarryBackground } from 'lib/components/StarryBackground'
import { userLogic } from 'scenes/userLogic'
import { Button, Row, Col } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { router } from 'kea-router'
import { PrevalidatedInvite } from '~/types'
import { Link } from 'lib/components/Link'
import { WhoAmI } from '~/layout/navigation/TopNavigation'
import { LoginSignup } from './LoginSignup'

const UTM_TAGS = 'utm_medium=in-product&utm_campaign=invite-signup'

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
        <Button icon={<ArrowLeftOutlined />} block onClick={() => push('/')}>
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
            <div className="inner">
                <div>
                    <h1 className="page-title">You have been invited to join {invite.organization_name}</h1>
                </div>
                <div>
                    You will accept the invite under your <b>existing PostHog account</b> ({user?.email})
                </div>
                <Row className="mt text-muted">
                    <Col span={24} md={12} style={{ textAlign: 'left' }}>
                        You can change organizations at any time by clicking on the dropdown at the top right corner of
                        the navigation bar.
                    </Col>
                    <Col md={12} span={0}>
                        {user && (
                            <div className="whoami-mock">
                                <div className="whoami-inner-container">
                                    <WhoAmI user={user} />
                                </div>
                            </div>
                        )}
                    </Col>
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
            </div>
        </div>
    )
}

export const InviteSignup = hot(_InviteSignup)
function _InviteSignup(): JSX.Element {
    const { invite, inviteLoading } = useValues(inviteSignupLogic)
    const { user } = useValues(userLogic)

    if (inviteLoading) {
        return <SceneLoading />
    }

    return (
        <div className={`invite-signup${user ? ' authenticated' : ''}`}>
            <ErrorView />
            {invite && (user ? <AuthenticatedAcceptInvite invite={invite} /> : <LoginSignup invite={invite} />)}
        </div>
    )
}
