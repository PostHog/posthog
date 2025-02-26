import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { SocialLoginIcon } from 'lib/components/SocialLoginButton/SocialLoginIcon'

import { githubSettingsLogic } from './githubSettingsLogic'

export const UserGithubAppSettings = (): JSX.Element => {
    const { installationUrl, isInstalled } = useValues(githubSettingsLogic)

    return (
        <div className="flex">
            <LemonButton size="medium" icon={<SocialLoginIcon provider="github" />} to={installationUrl}>
                <span>{isInstalled ? 'Manage Connection' : 'Connect GitHub'}</span>
            </LemonButton>
        </div>
    )
}
