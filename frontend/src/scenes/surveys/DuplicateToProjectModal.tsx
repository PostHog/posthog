import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal, LemonTag } from '@posthog/lemon-ui'

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
    const { duplicateToProject, setIsDuplicateToProjectModalOpen, duplicateSurvey } = useActions(surveyLogic)
    const { isDuplicateToProjectModalOpen, survey } = useValues(surveyLogic)
    const [selectedTeam, setSelectedTeam] = useState<TeamBasicType | null>(null)

    const handleCloseModal = (): void => {
        setIsDuplicateToProjectModalOpen(false)
        setSelectedTeam(null)
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
                        onClick={() => {
                            if (selectedTeam?.id === currentTeam?.id) {
                                return duplicateSurvey()
                            }

                            duplicateToProject({ sourceSurvey: survey, targetTeamId: selectedTeam?.id })
                        }}
                        loading={duplicatedToProjectSurveyLoading}
                        disabledReason={!selectedTeam ? 'Select a project' : undefined}
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
                                    onClick={() => setSelectedTeam(team)}
                                    active={selectedTeam?.id === team.id}
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
