import { useValues } from 'kea'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { teamLogic } from 'scenes/teamLogic'

export function ProjectTokenSnippet(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam?.api_token) {
        return null
    }

    return (
        <div className="flex items-center gap-1.5 min-w-0 text-xs" data-attr="onboarding-project-token">
            <span className="text-secondary shrink-0">Project token</span>
            <CopyToClipboardInline
                description="project token"
                iconSize="xsmall"
                tooltipMessage="Your SDKs send events to this project with it. It's safe to use in public apps. Click to copy."
                className="font-mono text-secondary min-w-0 bg-surface-secondary border border-primary rounded px-1.5 py-0.5"
            >
                {currentTeam.api_token}
            </CopyToClipboardInline>
        </div>
    )
}
