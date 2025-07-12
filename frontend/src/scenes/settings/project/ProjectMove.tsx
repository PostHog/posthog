import { useActions, useValues } from 'kea'
import { Dispatch, SetStateAction, useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { OrganizationBasicType } from '~/types'

export function MoveProjectModal({
    isOpen,
    setIsOpen,
    organization,
}: {
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
    organization: OrganizationBasicType
}): JSX.Element {
    const { currentProject, projectBeingMovedLoading } = useValues(projectLogic)
    const { moveProject } = useActions(projectLogic)

    const [isConfirmed, setConfirmed] = useState(false)

    return (
        <LemonModal
            title="Move the project to another organization?"
            onClose={!projectBeingMovedLoading ? () => setIsOpen(false) : undefined}
            closable={!projectBeingMovedLoading}
            maxWidth="30rem"
            footer={
                <>
                    <LemonButton
                        disabledReason={projectBeingMovedLoading && 'Moving...'}
                        type="secondary"
                        onClick={() => setIsOpen(false)}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        disabled={!isConfirmed}
                        loading={projectBeingMovedLoading}
                        data-attr="move-project-ok"
                        status="danger"
                        onClick={currentProject ? () => moveProject(currentProject, organization.id) : undefined}
                    >{`Move ${currentProject ? currentProject.name : 'the current project'}`}</LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                Moving a project will mean all original organization members will lose access including via things like
                API keys unless they also are part of the new organization.
            </p>
            <p>
                Please type <strong>{currentProject ? currentProject.name : "this project's name"}</strong> to confirm.
            </p>
            <LemonInput
                type="text"
                onChange={(value) => {
                    if (currentProject) {
                        setConfirmed(value.toLowerCase() === currentProject.name.toLowerCase())
                    }
                }}
            />
        </LemonModal>
    )
}

export function ProjectMove(): JSX.Element {
    const { currentProject } = useValues(projectLogic)
    const { otherOrganizations } = useValues(userLogic)
    const [isModalVisible, setIsModalVisible] = useState(false)

    const restrictedReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })

    const [targetOrganization, setTargetOrganization] = useState<OrganizationBasicType | null>(null)

    return (
        <>
            <p>
                Move <b>{currentProject?.name}</b> to another organization?
            </p>

            <div className="flex items-center gap-2">
                <LemonSelect
                    options={otherOrganizations.map((o) => ({
                        label: o.name,
                        value: o.id,
                    }))}
                    placeholder="Select target organization"
                    onChange={(value) => {
                        const organization = otherOrganizations.find((o) => o.id === value)
                        setTargetOrganization(organization || null)
                    }}
                    value={targetOrganization?.id}
                />

                <LemonButton
                    status="danger"
                    type="secondary"
                    onClick={() => setIsModalVisible(true)}
                    data-attr="move-project-button"
                    icon={<IconArrowRight />}
                    disabledReason={
                        restrictedReason ?? (targetOrganization === null && 'Please select the target organization')
                    }
                >
                    Move {currentProject?.name || 'the current project'}
                </LemonButton>
            </div>
            {targetOrganization && (
                <MoveProjectModal
                    isOpen={isModalVisible}
                    setIsOpen={setIsModalVisible}
                    organization={targetOrganization}
                />
            )}
        </>
    )
}
