import { LemonButton, LemonModal, LemonTag } from '@posthog/lemon-ui'
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
            Duplicate
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

    const handleCloseModal = (): void => {
        setIsDuplicateToProjectModalOpen(false)
        setSelectedProject(null)
    }

    return (
        <LemonModal
            title="Duplicate survey"
            onClose={handleCloseModal}
            isOpen={isDuplicateToProjectModalOpen}
            footer={
                <>
                    <LemonButton
                        disabledReason={duplicatedToProjectSurveyLoading ? 'Duplicating...' : undefined}
                        type="secondary"
                        onClick={handleCloseModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => duplicateToProject({ sourceSurvey: survey, targetTeamId: selectedProject?.id })}
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
                                        <div className="flex items-center gap-2">
                                            {team.id === currentTeam?.id && (
                                                <LemonTag size="small" type="primary" className="text-xs">
                                                    Current
                                                </LemonTag>
                                            )}
                                            {team.is_demo && (
                                                <LemonTag size="small" type="muted">
                                                    <span className="text-xs">Demo</span>
                                                </LemonTag>
                                            )}
                                        </div>
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
