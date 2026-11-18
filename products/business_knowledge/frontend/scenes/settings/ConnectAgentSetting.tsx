import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { AgentConfigSnippet } from './AgentConfigSnippet'
import { ConnectAgentAdminSteps } from './ConnectAgentAdminSteps'

export function ConnectAgentSetting(): JSX.Element {
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: TeamMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })

    const { currentTeam } = useValues(teamLogic)
    // The keys endpoint refuses a child environment, because business knowledge belongs to the project.
    const isChildEnvironment = !!currentTeam && currentTeam.id !== currentTeam.project_id
    const keyStep = restrictionReason
        ? 'Ask a project admin to create a key here. Only admins can create keys.'
        : isChildEnvironment
          ? "Switch to this project's main environment to create a key. Business knowledge keys belong to the project."
          : null

    return (
        <div className="flex flex-col gap-3 max-w-xl">
            {keyStep ? (
                <>
                    <ol className="m-0 pl-5 flex flex-col gap-2 list-decimal">
                        <li>{keyStep}</li>
                        <li>
                            Add the PostHog MCP server to your agent, and replace the placeholder with the key. Most
                            agents accept this format:
                        </li>
                    </ol>
                    <AgentConfigSnippet />
                </>
            ) : (
                <ConnectAgentAdminSteps />
            )}
            <p className="m-0 text-secondary">
                The agent gets tools to search your sources, read around a result, list libraries, and search and read
                your selected repositories. It cannot change anything, and it cannot read other PostHog data.
            </p>
            <LemonBanner type="warning">
                Keep the key on your server. Anyone who has it can read the business knowledge the key covers, so do not
                put it in a website or a mobile app.
            </LemonBanner>
        </div>
    )
}
