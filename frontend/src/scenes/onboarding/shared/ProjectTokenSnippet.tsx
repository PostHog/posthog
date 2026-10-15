import { useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'

export function ProjectTokenSnippet(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam?.api_token) {
        return null
    }

    return (
        <div className="flex flex-col gap-1 min-w-0" data-attr="onboarding-project-token">
            <LemonLabel className="mb-0">Your project token</LemonLabel>
            <CodeSnippet compact thing="project token">
                {currentTeam.api_token}
            </CodeSnippet>
            <p className="text-xs text-muted mb-0">
                Your SDKs send events to this project with it. Safe to use in public apps.
            </p>
        </div>
    )
}
