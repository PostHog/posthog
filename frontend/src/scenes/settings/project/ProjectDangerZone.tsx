import { useActions, useValues } from 'kea'
import { Dispatch, SetStateAction, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'

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
    const isDeletionInProgress = !!currentProject && projectBeingDeleted?.id === currentProject.id

    const allTeamsOfProject =
        currentProject && currentOrganization
            ? currentOrganization.teams.filter((team) => team.project_id === currentProject.id)
            : []

    return (
        <LemonModal
            title="Delete the project and its data?"
            onClose={!isDeletionInProgress ? () => setIsOpen(false) : undefined}
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
                        onClick={currentProject ? () => deleteProject(currentProject) : undefined}
                    >{`Delete ${currentProject ? currentProject.name : 'the current project'}`}</LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                You will lose all environments and their data (<b>including events</b>):
                <ul className="list-disc list-inside ml-4 mt-1">
                    {allTeamsOfProject.map((team) => (
                        <li key={team.id}>{team.name}</li>
                    ))}
                </ul>
            </p>
            <div className="mt-2 p-2 bg-bg-3000 rounded text-sm deprecated-space-y-2">
                <p>
                    Deletion starts in <strong>48 hours</strong>. Until then nobody can open the project, and you can
                    cancel the deletion from the screen you land on next. A project that never received events is
                    deleted right away.
                </p>
                <p>
                    Once deletion starts, it <b>cannot be undone</b>. Cleanup can take several hours for a project with
                    lots of data. We'll email you when it's done.
                </p>
            </div>
            <p className="mt-2">
                Please type <strong>{currentProject ? currentProject.name : "this project's name"}</strong> to confirm.
            </p>
            <LemonInput
                type="text"
                onChange={(value) => {
                    if (currentProject) {
                        setIsDeletionConfirmed(value.toLowerCase() === currentProject.name.toLowerCase())
                    }
                }}
            />
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

    return (
        <>
            <div className="text-danger">
                <div className="mt-4">
                    {!restrictedReason && (
                        <p className="text-danger">
                            Once deletion starts, this <b>cannot be undone</b>. Please be certain.
                        </p>
                    )}
                    <LemonButton
                        status="danger"
                        type="secondary"
                        onClick={() => setIsModalVisible(true)}
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
