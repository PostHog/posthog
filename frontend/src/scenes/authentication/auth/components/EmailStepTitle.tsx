import { useValues } from 'kea'

import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { useLastLoginMethod } from 'scenes/authentication/shared/lastLoginMethod'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'

import { authLogic, hasSingleSignOn } from '../authLogic'
import { loginLogic } from '../loginLogic'
import { ConnectTitle } from './ConnectTitle'
import { HighlightedName } from './HighlightedName'

function LoginTitle(): JSX.Element {
    const { precheckResponse } = useValues(loginLogic)
    const { entry, accountExists } = useValues(authLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    const greeting =
        accountExists === false
            ? 'Nice to meet you.'
            : accountExists === null
              ? 'Hi there.'
              : entry === 'signup'
                ? 'Plot twist: this email already has an account.'
                : 'Good to see you.'

    if (pendingConnection) {
        return (
            <AuthCardTitle
                title={<ConnectTitle lead="Log in to connect" clientName={pendingConnection.clientName} />}
                sub={greeting}
            />
        )
    }
    if (accountExists === false) {
        return (
            <AuthCardTitle
                title={hasSingleSignOn(precheckResponse) ? 'Your team uses single sign-on' : 'No account here yet'}
                sub={greeting}
            />
        )
    }
    return <AuthCardTitle title={accountExists === null ? 'Log in' : 'Welcome back'} sub={greeting} />
}

function SignupTitle(): JSX.Element {
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    return (
        <AuthCardTitle
            title={
                pendingConnection ? (
                    <ConnectTitle lead="Create your account to connect" clientName={pendingConnection.clientName} />
                ) : (
                    'Create your account'
                )
            }
            sub="There's no account for this email yet. Choose a password to create one."
        />
    )
}

export function EmailStepTitle(): JSX.Element {
    const { entry, step } = useValues(authLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)
    const isReturning = useLastLoginMethod() !== null

    if (step === 'login') {
        return <LoginTitle />
    }
    if (step === 'signup_credentials') {
        return <SignupTitle />
    }
    if (pendingConnection) {
        return (
            <AuthCardTitle
                title={<ConnectTitle lead="Log in or sign up to connect" clientName={pendingConnection.clientName} />}
                sub={`${pendingConnection.clientName} saved you a seat.`}
            />
        )
    }
    if (entry === 'signup') {
        return <AuthCardTitle title="Get started" sub="Make your product self-driving." />
    }
    return (
        <AuthCardTitle
            title={
                <>
                    <span>{isReturning ? 'Log in to ' : 'Log in or sign up to '}</span>
                    <HighlightedName>@PostHog</HighlightedName>
                </>
            }
            sub={isReturning ? "Welcome back. Let's go ship something." : 'Hedgehogs of all kinds welcome.'}
        />
    )
}
