import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'

import { GRAVATAR_MANAGE_URL } from 'lib/utils/gravatar'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { GravatarStatus, profilePictureLogic } from './profilePictureLogic'

function gravatarDescription(status: GravatarStatus, email: string): JSX.Element {
    const maskedEmail = <span className="ph-no-capture">{email}</span>
    switch (status) {
        case 'unknown':
            return <>Checking Gravatar for {maskedEmail}.</>
        case 'found':
            return (
                <>
                    This picture comes from Gravatar, matched to {maskedEmail}. Change it there, then check again to see
                    it here.
                </>
            )
        case 'missing':
            return (
                <>
                    No picture yet. Add one on Gravatar for {maskedEmail} and it shows here and anywhere teammates see
                    you.
                </>
            )
    }
}

export function ProfilePictureSettings(): JSX.Element {
    const { user } = useValues(userLogic)
    const { gravatarStatus, gravatarChecking, gravatarEmail, gravatarRefreshKey, usesHedgehogAsProfilePicture } =
        useValues(profilePictureLogic)
    const { recheckGravatar } = useActions(profilePictureLogic)

    const email = user?.email || 'your email'

    return (
        <div className="flex items-center gap-4">
            <ProfilePicture
                key={`${gravatarEmail}:${gravatarRefreshKey}`}
                user={user}
                size="xxl"
                refreshKey={gravatarRefreshKey}
            />
            <div className="flex min-w-0 flex-col gap-2">
                {usesHedgehogAsProfilePicture ? (
                    <>
                        <p className="m-0 text-sm text-secondary">
                            Your hedgehog is your profile picture. Turn that off to show your Gravatar instead.
                        </p>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                type="secondary"
                                to={urls.settings('user-customization', 'hedgehog-mode')}
                                data-attr="settings-profile-picture-hedgehog"
                            >
                                Hedgehog mode settings
                            </LemonButton>
                        </div>
                    </>
                ) : (
                    <>
                        <p className="m-0 text-sm text-secondary">{gravatarDescription(gravatarStatus, email)}</p>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                type="secondary"
                                to={GRAVATAR_MANAGE_URL}
                                targetBlank
                                data-attr="settings-profile-picture-gravatar"
                            >
                                {gravatarStatus === 'found' ? 'Change on Gravatar' : 'Add on Gravatar'}
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                icon={<IconRefresh />}
                                loading={gravatarChecking}
                                onClick={recheckGravatar}
                                data-attr="settings-profile-picture-refresh"
                            >
                                Check again
                            </LemonButton>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
