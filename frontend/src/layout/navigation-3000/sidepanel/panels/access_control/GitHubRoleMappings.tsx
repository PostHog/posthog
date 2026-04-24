import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGithub } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { AttachGitHubTeamModal } from './AttachGitHubTeamModal'
import { githubRoleMappingsLogic } from './githubRoleMappingsLogic'
import { GitHubRoleMappingsTable } from './GitHubRoleMappingsTable'

export function GitHubRoleMappings({
    roleId,
    canEditRoles,
}: {
    roleId: string
    canEditRoles: boolean | null
}): JSX.Element | null {
    const logic = githubRoleMappingsLogic({ roleId })
    const { organizationGithubIntegrations, githubReferencesForRole } = useValues(logic)
    const { openExternalReferenceModal, deleteRoleExternalReference } = useActions(logic)

    return (
        <div className="rounded border border-border p-3 deprecated-space-y-2">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <IconGithub fontSize="18" />
                    <h4 className="mb-0 text-sm font-semibold">GitHub</h4>
                </div>
                {organizationGithubIntegrations.length > 0 ? (
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={openExternalReferenceModal}
                        disabledReason={!canEditRoles ? 'You cannot edit this' : undefined}
                    >
                        Attach GitHub team
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => router.actions.push(urls.settings('environment-integrations'))}
                    >
                        GitHub connection
                    </LemonButton>
                )}
            </div>

            <div className="text-xs text-muted">
                Use GitHub teams from organization installations to map external roles.
            </div>

            <GitHubRoleMappingsTable
                references={githubReferencesForRole}
                canEditRoles={canEditRoles}
                onDelete={deleteRoleExternalReference}
            />

            {organizationGithubIntegrations.length > 0 ? (
                <AttachGitHubTeamModal roleId={roleId} canEditRoles={canEditRoles} />
            ) : null}
        </div>
    )
}
