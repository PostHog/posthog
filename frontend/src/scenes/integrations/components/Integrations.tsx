import { useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { cn } from 'lib/utils/css-classes'
import { GitLabSetupModal } from 'scenes/integrations/gitlab/GitLabSetupModal'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { IntegrationKind } from '~/types'

import { Integration } from './Integration'

export { GithubIntegration, GitHubInstallationLink } from './GithubIntegration'

export function GitLabIntegration({ centered }: { centered?: boolean } = {}): JSX.Element {
    const [isOpen, setIsOpen] = useState<boolean>(false)
    return (
        <Integration kind="gitlab" centered={centered}>
            <LemonButton type="secondary" onClick={() => setIsOpen(true)}>
                Connect project
            </LemonButton>
            <GitLabSetupModal isOpen={isOpen} onComplete={() => setIsOpen(false)} />
        </Integration>
    )
}

export function LinearIntegration({ next, centered }: { next?: string; centered?: boolean }): JSX.Element {
    // Switching workspace on Linear's approval screen drops the OAuth request, so the workspace
    // has to be selected in Linear before the flow starts.
    return (
        <OAuthIntegration
            kind="linear"
            connectText="Connect workspace"
            next={next}
            centered={centered}
            hint={
                <>
                    Before connecting, open Linear in a new tab and switch to the workspace you want to connect to. Then
                    come back here and click <strong>Connect workspace</strong>.
                </>
            }
        />
    )
}

export function JiraIntegration({ next, centered }: { next?: string; centered?: boolean }): JSX.Element {
    return <OAuthIntegration kind="jira" connectText="Connect site" next={next} centered={centered} />
}

const OAuthIntegration = ({
    kind,
    connectText,
    next,
    centered,
    hint,
}: {
    kind: IntegrationKind
    connectText: string
    next?: string
    centered?: boolean
    hint?: ReactNode
}): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const settingsPath = next ?? urls.settings('environment-integrations')
    const authorizationUrl = api.integrations.authorizeUrl({
        next: currentTeam?.id ? urls.project(currentTeam.id, settingsPath) : settingsPath,
        kind,
    })

    const connectButton = (
        <LemonButton type="secondary" disableClientSideRouting to={authorizationUrl}>
            {connectText}
        </LemonButton>
    )

    return (
        <Integration kind={kind} centered={centered}>
            {hint ? (
                <div className={cn('flex flex-col gap-y-4', centered ? 'items-center text-center' : 'items-start')}>
                    {connectButton}
                    <p className="m-0 text-xs text-secondary">{hint}</p>
                </div>
            ) : (
                connectButton
            )}
        </Integration>
    )
}
