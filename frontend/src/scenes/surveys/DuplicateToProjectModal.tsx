import { LemonButton, LemonModal, lemonToast } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { TeamBasicType } from '~/types'

import { surveyLogic } from './surveyLogic'

export function DuplicateToProjectTrigger(): JSX.Element {
    const { setIsDuplicateToProjectModalOpen } = useActions(surveyLogic)

    return (
        <LemonButton fullWidth onClick={() => setIsDuplicateToProjectModalOpen(true)}>
            Duplicate to another project
        </LemonButton>
    )
}

export function DuplicateToProjectModal(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { duplicatedToProjectSurveyLoading } = useValues(surveyLogic)
    const { duplicateToProject, setIsDuplicateToProjectModalOpen } = useActions(surveyLogic)
    const { isDuplicateToProjectModalOpen, survey } = useValues(surveyLogic)
    const [selectedProject, setSelectedProject] = useState<TeamBasicType | null>(null)

    return (
        <LemonModal
            title="Duplicate survey to another project"
            onClose={() => setIsDuplicateToProjectModalOpen(false)}
            isOpen={isDuplicateToProjectModalOpen}
            footer={
                <>
                    <LemonButton
                        disabledReason={duplicatedToProjectSurveyLoading ? 'Duplicating...' : undefined}
                        type="secondary"
                        onClick={() => setIsDuplicateToProjectModalOpen(false)}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            if (selectedProject) {
                                duplicateToProject({ sourceSurvey: survey, targetTeamId: selectedProject.id })
                                setIsDuplicateToProjectModalOpen(false)
                            } else {
                                lemonToast.error('Please select a project to duplicate to')
                            }
                        }}
                        loading={duplicatedToProjectSurveyLoading}
                        disabledReason={!selectedProject ? 'Select a project' : undefined}
                    >
                        Duplicate
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <p>
                    Select a project to duplicate this survey to. The survey will be created as a draft with the same
                    settings.
                </p>
                <div className="space-y-2">
                    <h4 className="font-semibold">Projects:</h4>
                    <div className="space-y-2 max-h-80 overflow-y-auto border rounded p-2">
                        {currentOrganization?.teams
                            ?.filter((team) => team.id !== currentTeam?.id)
                            .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                            .map((team) => (
                                <LemonButton
                                    key={team.id}
                                    onClick={() => setSelectedProject(team)}
                                    active={selectedProject?.id === team.id}
                                    fullWidth
                                >
                                    <div className="flex items-center justify-between w-full">
                                        <span>{team.name}</span>
                                        {team.is_demo && <span className="text-xs text-muted">Demo</span>}
                                    </div>
                                </LemonButton>
                            ))}
                        {(!currentOrganization?.teams || currentOrganization.teams.length <= 1) && (
                            <div className="text-center p-2 text-muted">No other projects available</div>
                        )}
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
