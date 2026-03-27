import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { Experiment } from '~/types'

interface CopyExperimentToProjectModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}

export function CopyExperimentToProjectModal({
    isOpen,
    onClose,
    experiment,
}: CopyExperimentToProjectModalProps): JSX.Element {
    const { copyExperimentToProject } = useActions(experimentsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)

    const handleCopy = (): void => {
        if (selectedProjectId) {
            copyExperimentToProject({ id: experiment.id as number, targetProjectId: selectedProjectId })
            handleClose()
        }
    }

    const handleClose = (): void => {
        setSelectedProjectId(null)
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="Copy experiment to project" width={480}>
            <div className="space-y-4">
                <div className="text-muted">
                    The experiment and its feature flag will be copied as a draft. The feature flag will be disabled by
                    default in the target project.
                </div>
                <div>
                    <div className="font-semibold mb-2">Destination project</div>
                    <LemonSelect
                        placeholder="Select a project"
                        fullWidth
                        dropdownMatchSelectWidth={false}
                        value={selectedProjectId}
                        onChange={(id) => setSelectedProjectId(id)}
                        options={
                            currentOrganization?.teams
                                ?.map((team) => ({ value: team.project_id, label: team.name }))
                                .sort((a, b) => a.label.localeCompare(b.label))
                                .filter((option) => option.value !== currentTeam?.project_id) || []
                        }
                    />
                </div>
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        disabledReason={!selectedProjectId ? 'Select a project' : undefined}
                        onClick={handleCopy}
                    >
                        Copy
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}
