import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { Dispatch, SetStateAction, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

export function DeleteProjectModal({
    isOpen,
    setIsOpen,
}: {
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { currentTeam, teamBeingDeleted } = useValues(teamLogic)
    const { deleteTeam } = useActions(teamLogic)

    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const isDeletionInProgress = !!currentTeam && teamBeingDeleted?.id === currentTeam.id

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
                        onClick={currentTeam ? () => deleteTeam(currentTeam as TeamType) : undefined}
                    >{`Delete ${currentTeam ? currentTeam.name : 'the current project'}`}</LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                Project deletion <b>cannot be undone</b>. You will lose all data, <b>including events</b>, related to
                the project.
            </p>
            <p>
                Please type <strong>{currentTeam ? currentTeam.name : "this project's name"}</strong> to confirm.
            </p>
            <LemonInput
                type="text"
                onChange={(value) => {
                    if (currentTeam) {
                        setIsDeletionConfirmed(value.toLowerCase() === currentTeam.name.toLowerCase())
                    }
                }}
            />
        </LemonModal>
    )
}

export function ProjectDangerZone(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
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
                            This is <b>irreversible</b>. Please be certain.
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
                        Delete {currentTeam?.name || 'the current project'}
                    </LemonButton>
                </div>
            </div>
            <DeleteProjectModal isOpen={isModalVisible} setIsOpen={setIsModalVisible} />
        </>
    )
}
