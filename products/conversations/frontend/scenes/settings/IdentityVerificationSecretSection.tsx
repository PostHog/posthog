import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { signingSecretLogic } from './signingSecretLogic'

export function IdentityVerificationSecretSection(): JSX.Element {
    const { signingSecret, signingSecretLoading, signingSecretLoadFailed } = useValues(signingSecretLogic)
    const { rotateSigningSecret, loadSigningSecret, expirePreviousSecret } = useActions(signingSecretLogic)
    const { isTeamTokenResetAvailable } = useValues(teamLogic)

    const secret = signingSecret?.secret ?? null
    // Null once the window lapses: the API only reports an active grace window.
    const previousSecretValidUntil = signingSecret?.previous_secret_valid_until ?? null

    const openRotateDialog = (): void => {
        const verb = secret ? 'Rotate' : 'Generate'
        const description = secret
            ? 'This generates a new secret right away. The current secret keeps verifying for 48 hours so you can update your server-side code, then it expires.'
            : 'This generates a secret for verifying the identity of users in the support widget.'

        LemonDialog.open({
            title: `${verb} identity verification secret?`,
            description,
            primaryButton: {
                children: verb,
                onClick: rotateSigningSecret,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const openExpirePreviousDialog = (): void => {
        LemonDialog.open({
            title: 'Expire the previous secret now?',
            description:
                'Identity hashes signed with the previous secret stop verifying immediately. Do this if it may be compromised, or once all your servers use the new secret.',
            primaryButton: {
                children: 'Expire now',
                status: 'danger',
                onClick: expirePreviousSecret,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <SceneSection
            title="Identity verification secret"
            titleSize="sm"
            description="Signs the identity hashes that verify who a user is in the support widget. Only use it server-side and keep it out of client code."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                {signingSecretLoading && !signingSecret ? (
                    <LemonSkeleton className="h-10" />
                ) : signingSecretLoadFailed ? (
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadSigningSecret() }}>
                        Couldn't load the identity verification secret. Retry, and if it keeps happening contact
                        support.
                    </LemonBanner>
                ) : (
                    <>
                        <CodeSnippet
                            actions={
                                <LemonButton
                                    icon={<IconRefresh />}
                                    size="xsmall"
                                    data-attr="conversations-rotate-signing-secret"
                                    onClick={openRotateDialog}
                                    loading={signingSecretLoading}
                                    disabledReason={
                                        !isTeamTokenResetAvailable
                                            ? 'You do not have permission to rotate this secret'
                                            : undefined
                                    }
                                    tooltip={secret ? 'Rotate secret' : 'Generate secret'}
                                />
                            }
                            className={secret ? '' : 'text-muted'}
                            thing="Identity verification secret"
                        >
                            {secret ||
                                'No secret yet. Generate one with the button on the right to enable identity verification.'}
                        </CodeSnippet>

                        {previousSecretValidUntil ? (
                            <LemonBanner
                                type="info"
                                className="my-2"
                                action={{
                                    children: 'Expire now',
                                    'data-attr': 'conversations-expire-previous-signing-secret',
                                    disabledReason: !isTeamTokenResetAvailable
                                        ? 'You do not have permission to expire the previous secret'
                                        : undefined,
                                    onClick: openExpirePreviousDialog,
                                }}
                            >
                                The previous secret keeps verifying until{' '}
                                <TZLabel time={previousSecretValidUntil} formatDate="MMM D, YYYY" formatTime="h:mm A" />
                                . Update your server-side code with the new secret before then, or expire it now if it
                                may be compromised.
                            </LemonBanner>
                        ) : secret ? (
                            <LemonBanner type="info" className="my-2">
                                Rotating this secret starts a 48-hour grace window: the previous secret keeps verifying
                                until the window ends, then expires. Update your server-side code within that window.
                            </LemonBanner>
                        ) : (
                            <LemonBanner type="info" className="my-2">
                                This project doesn't have an identity verification secret yet. Identity verification in
                                the support widget stays off until you generate one.
                            </LemonBanner>
                        )}
                    </>
                )}
            </LemonCard>
        </SceneSection>
    )
}
