import { useValues } from 'kea'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { inviteSignupLogic, ErrorCodes } from './inviteSignupLogic'
import { SceneLoading } from 'lib/utils'
import './InviteSignup.scss'
import { StarryBackground } from 'lib/components/StarryBackground'

const UTM_TAGS = 'utm_medium=in-product&utm_campaign=invite-signup'

interface ErrorMessage {
    title: string
    detail: JSX.Element | string
    actions: JSX.Element
}

const HelperLinks = (
    <>
        <a href="/">App Home</a>
        <a href={`https://posthog.com?${UTM_TAGS}&utm_message=invalid-invite`} rel="noopener">
            PostHog Website
        </a>
        <a href={`https://posthog.com/slack?${UTM_TAGS}&utm_message=invalid-invite`} rel="noopener">
            Contact Us
        </a>
    </>
)

const ErrorMessages: Record<ErrorCodes, ErrorMessage> = {
    [ErrorCodes.InvalidInvite]: {
        title: 'Oops! This invite link is invalid or has expired',
        detail: (
            <>
                If you believe this is a mistake, please contact whoever created this invite and{' '}
                <b>ask them for a new invite</b>.
            </>
        ),
        actions: HelperLinks,
    },
    [ErrorCodes.Unknown]: {
        title: 'Oops! We could not validate this invite link',
        detail:
            'There was an issue with your invite link, please try again in a few seconds. If the problem persists, contact us.',
        actions: HelperLinks,
    },
}

function ErrorView(): JSX.Element | null {
    const { error } = useValues(inviteSignupLogic)

    if (!error) {
        return null
    }

    return (
        <div className="error-view">
            <StarryBackground>
                <div className="error-view-container">
                    <div className="inner">
                        <h1 className="page-title">{ErrorMessages[error].title}</h1>
                        <div className="error-message">{ErrorMessages[error].detail}</div>
                        <div className="actions">{ErrorMessages[error].actions}</div>
                    </div>
                </div>
            </StarryBackground>
        </div>
    )
}

export const InviteSignup = hot(_InviteSignup)
function _InviteSignup(): JSX.Element {
    const { invite, inviteLoading, error } = useValues(inviteSignupLogic)

    if (inviteLoading) {
        return <SceneLoading />
    }

    return (
        <div className="invite-signup">
            <ErrorView />
            {!error && <div className="invite-signup-form">Hello there! {invite?.target_email}</div>}
        </div>
    )
}
