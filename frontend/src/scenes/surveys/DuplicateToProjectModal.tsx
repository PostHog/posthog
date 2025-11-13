import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { teamLogic } from 'scenes/teamLogic'

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
    const { duplicateToProject, setIsDuplicateToProjectModalOpen, duplicateSurvey } = useActions(surveyLogic)
    const { isDuplicateToProjectModalOpen, survey, duplicatedToProjectSurveyLoading } = useValues(surveyLogic)
    const [selectedTeamIds, setSelectedTeamIds] = useState<Set<number>>(new Set())

    const availableTeams = useMemo(
        () => currentOrganization?.teams.sort((teamA, teamB) => teamA.name.localeCompare(teamB.name)) || [],
        [currentOrganization?.teams]
    )

    const allTeamIds = useMemo(() => new Set(availableTeams.map((team) => team.id)), [availableTeams])

    const allSelected = selectedTeamIds.size === availableTeams.length && availableTeams.length > 0
    const someSelected = selectedTeamIds.size > 0 && selectedTeamIds.size < availableTeams.length

    const handleCloseModal = (): void => {
        setIsDuplicateToProjectModalOpen(false)
        setSelectedTeamIds(new Set())
    }

    const handleToggleTeam = (teamId: number): void => {
        const newSelection = new Set(selectedTeamIds)
        if (newSelection.has(teamId)) {
            newSelection.delete(teamId)
        } else {
            newSelection.add(teamId)
        }
        setSelectedTeamIds(newSelection)
    }

    const handleToggleAll = (): void => {
        if (allSelected) {
            setSelectedTeamIds(new Set())
        } else {
            setSelectedTeamIds(allTeamIds)
        }
    }

    const handleDuplicate = (): void => {
        const selectedTeamIdsArray = Array.from(selectedTeamIds)

        // Check if only current team is selected
        if (selectedTeamIdsArray.length === 1 && selectedTeamIdsArray[0] === currentTeam?.id) {
            return duplicateSurvey()
        }

        // Use bulk duplication for all selected teams
        duplicateToProject({ sourceSurvey: survey, targetTeamIds: selectedTeamIdsArray })
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
                        onClick={handleDuplicate}
                        loading={duplicatedToProjectSurveyLoading}
                        disabledReason={selectedTeamIds.size === 0 ? 'Select at least one project' : undefined}
                    >
                        Duplicate to {selectedTeamIds.size} project{selectedTeamIds.size !== 1 ? 's' : ''}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <p>
                    <strong>Select one or more projects to duplicate this survey to.</strong> The survey will be created
                    as a draft with the same settings in each selected project.
                </p>
                <div className="space-y-2">
                    <div className="flex items-center gap-3 p-2 border-b">
                        {availableTeams.length > 1 && (
                            <>
                                <LemonCheckbox
                                    checked={allSelected ? true : someSelected ? 'indeterminate' : false}
                                    onChange={handleToggleAll}
                                />
                                <span className="font-semibold">{allSelected ? 'Deselect All' : 'Select All'}</span>
                            </>
                        )}
                        {availableTeams.length <= 1 && <h4 className="font-semibold">Projects:</h4>}
                    </div>
                    <div className="space-y-1 max-h-80 overflow-y-auto border rounded p-2">
                        {availableTeams.map((team) => (
                            <label
                                key={team.id}
                                htmlFor={`project-${team.id}`}
                                className="flex items-center gap-3 p-2 rounded hover:bg-border-light cursor-pointer"
                            >
                                <LemonCheckbox
                                    id={`project-${team.id}`}
                                    checked={selectedTeamIds.has(team.id)}
                                    onChange={() => handleToggleTeam(team.id)}
                                />
                                <div className="flex items-center justify-between flex-1">
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
                            </label>
                        ))}
                        {(!currentOrganization?.teams || currentOrganization.teams.length === 0) && (
                            <div className="text-center p-2 text-muted">No projects available</div>
                        )}
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
