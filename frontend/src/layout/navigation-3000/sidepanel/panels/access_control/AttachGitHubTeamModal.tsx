import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { githubRoleMappingsLogic, getIntegrationAccountName } from './githubRoleMappingsLogic'

export function AttachGitHubTeamModal({
    roleId,
    canEditRoles,
}: {
    roleId: string
    canEditRoles: boolean | null
}): JSX.Element {
    const logic = githubRoleMappingsLogic({ roleId })
    const {
        externalReferenceModalOpen,
        selectedGithubIntegrationId,
        selectedGithubTeamId,
        organizationGithubIntegrations,
        availableGithubTeams,
        noTeamsHelpText,
        canAttachSelectedGithubTeam,
    } = useValues(logic)
    const {
        closeExternalReferenceModal,
        setSelectedGithubIntegrationId,
        setSelectedGithubTeamId,
        attachSelectedGithubTeam,
    } = useActions(logic)

    return (
        <LemonModal
            isOpen={externalReferenceModalOpen}
            onClose={closeExternalReferenceModal}
            title="Attach GitHub team"
            maxWidth={560}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeExternalReferenceModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={attachSelectedGithubTeam}
                        disabledReason={
                            !canEditRoles
                                ? 'You cannot edit this'
                                : availableGithubTeams.length === 0
                                  ? 'No unattached GitHub teams available'
                                  : !canAttachSelectedGithubTeam
                                    ? 'Select an integration and team to attach'
                                    : undefined
                        }
                    >
                        Attach
                    </LemonButton>
                </>
            }
        >
            <div className="deprecated-space-y-3">
                <LemonSelect
                    value={selectedGithubIntegrationId}
                    onChange={(value) => {
                        setSelectedGithubIntegrationId(value)
                        setSelectedGithubTeamId(null)
                    }}
                    options={organizationGithubIntegrations.map((integration) => ({
                        value: integration.id,
                        label: getIntegrationAccountName(integration) || `Integration ${integration.id}`,
                    }))}
                    placeholder="Select GitHub organization"
                    fullWidth
                />
                <LemonSelect
                    value={selectedGithubTeamId}
                    onChange={setSelectedGithubTeamId}
                    options={availableGithubTeams.map((team) => ({
                        value: team.id,
                        label: `${team.name} (${team.slug})`,
                    }))}
                    placeholder="Select GitHub team"
                    disabledReason={availableGithubTeams.length === 0 ? noTeamsHelpText : undefined}
                    fullWidth
                />
                {availableGithubTeams.length === 0 && <div className="text-xs text-muted">{noTeamsHelpText}</div>}
            </div>
        </LemonModal>
    )
}
