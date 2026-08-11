import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { GitLabSetupModal } from 'scenes/integrations/gitlab/GitLabSetupModal'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { IntegrationKind } from '~/types'

import { Integration } from './Integration'

export { GithubIntegration, GitHubInstallationLink } from './GithubIntegration'

export function GitLabIntegration(): JSX.Element {
    const [isOpen, setIsOpen] = useState<boolean>(false)
    return (
        <Integration kind="gitlab">
            <LemonButton type="secondary" onClick={() => setIsOpen(true)}>
                Connect project
            </LemonButton>
            <GitLabSetupModal isOpen={isOpen} onComplete={() => setIsOpen(false)} />
        </Integration>
    )
}

export function LinearIntegration({ next }: { next?: string }): JSX.Element {
    return <OAuthIntegration kind="linear" connectText="Connect workspace" next={next} />
}

export function JiraIntegration({ next }: { next?: string }): JSX.Element {
    return <OAuthIntegration kind="jira" connectText="Connect site" next={next} />
}

const OAuthIntegration = ({
    kind,
    connectText,
    next,
}: {
    kind: IntegrationKind
    connectText: string
    next?: string
}): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const settingsPath = next ?? urls.settings('environment-integrations')
    const authorizationUrl = api.integrations.authorizeUrl({
        next: currentTeam?.id ? urls.project(currentTeam.id, settingsPath) : settingsPath,
        kind,
    })

    return (
        <Integration kind={kind}>
            <LemonButton type="secondary" disableClientSideRouting to={authorizationUrl}>
                {connectText}
            </LemonButton>
        </Integration>
    )
}
