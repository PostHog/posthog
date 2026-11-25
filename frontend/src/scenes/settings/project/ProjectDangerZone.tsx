import { useActions, useValues } from 'kea'
import { Dispatch, SetStateAction, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'

import { QuillDeleteProjectDialog } from './QuillDeleteProjectDialog'

export function DeleteProjectModal({
    isOpen,
    setIsOpen,
}: {
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { currentProject, projectBeingDeleted } = useValues(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { deleteProject } = useActions(projectLogic)

    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const isDeletionInProgress = !!currentProject && projectBeingDeleted?.id === currentProject.id

    const allTeamsOfProject =
        currentProject && currentOrganization
            ? currentOrganization.teams.filter((team) => team.project_id === currentProject.id)
            : []

    const closeModal = !isDeletionInProgress ? () => setIsOpen(false) : undefined
    const deleteCurrentProject = currentProject ? () => deleteProject(currentProject) : undefined
    const handleConfirmationChange = (value: string): void => {
        if (currentProject) {
            setIsDeletionConfirmed(value.toLowerCase() === currentProject.name.toLowerCase())
        }
    }

    if (todayRailNav) {
        return (
            <QuillDeleteProjectDialog
                isOpen={isOpen}
                onClose={closeModal}
                onCancel={() => setIsOpen(false)}
                projectName={currentProject?.name}
                environmentNames={allTeamsOfProject.map((team) => ({ id: team.id, name: team.name }))}
                isDeletionConfirmed={isDeletionConfirmed}
                isDeletionInProgress={isDeletionInProgress}
                onConfirmationChange={handleConfirmationChange}
                onDelete={deleteCurrentProject}
            />
        )
    }

    return (
        <LemonModal
            title="Delete the project and its data?"
            onClose={closeModal}
            footer={
                <>
                    <LemonButton
                        disabledReason={isDeletionInProgress && 'Deleting...'}
                        type="secondary"
                        onClick={() => setIsOpen(false)}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        disabled={!isDeletionConfirmed}
                        loading={isDeletionInProgress}
                        data-attr="delete-project-ok"
                        status="danger"
                        onClick={deleteCurrentProject}
                    >{`Delete ${currentProject ? currentProject.name : 'the current project'}`}</LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                Project deletion <b>cannot be undone</b>. You will lose all environments and their data (
                <b>including events</b>):
                <ul className="list-disc list-inside ml-4 mt-1">
                    {allTeamsOfProject.map((team) => (
                        <li key={team.id}>{team.name}</li>
                    ))}
                </ul>
            </p>
            <p className="mt-2 p-2 bg-bg-3000 rounded text-sm">
                <strong>Note:</strong> For projects with lots of data, cleanup may take several hours. We'll send you an
                email when the process is complete.
            </p>
            <p>
                Please type <strong>{currentProject ? currentProject.name : "this project's name"}</strong> to confirm.
            </p>
            <LemonInput type="text" onChange={handleConfirmationChange} />
        </LemonModal>
    )
}

export function ProjectDangerZone(): JSX.Element {
    const { currentProject } = useValues(projectLogic)
    const [isModalVisible, setIsModalVisible] = useState(false)

    const restrictedReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const openModal = (): void => setIsModalVisible(true)

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-2">
                {!restrictedReason && (
                    <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                        This is <b>irreversible</b>. Please be certain.
                    </Text>
                )}
                <Button
                    variant="destructive-outline"
                    onClick={openModal}
                    data-attr="delete-project-button"
                    disabledReason={restrictedReason}
                >
                    <IconTrash />
                    Delete {currentProject?.name || 'the current project'}
                </Button>
                <DeleteProjectModal isOpen={isModalVisible} setIsOpen={setIsModalVisible} />
            </div>
        )
    }

    return (
        <>
            <div className="text-danger">
                <div className="mt-4">
                    {!restrictedReason && (
                        <p className="text-danger">
                            This is <b>irreversible</b>. Please be certain.
                        </p>
                    )}
                    <LemonButton
                        status="danger"
                        type="secondary"
                        onClick={openModal}
                        data-attr="delete-project-button"
                        icon={<IconTrash />}
                        disabledReason={restrictedReason}
                    >
                        Delete {currentProject?.name || 'the current project'}
                    </LemonButton>
                </div>
            </div>
            <DeleteProjectModal isOpen={isModalVisible} setIsOpen={setIsModalVisible} />
        </>
    )
}
