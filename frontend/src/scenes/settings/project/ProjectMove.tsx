import { useActions, useValues } from 'kea'
import { Dispatch, SetStateAction, useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSearchableSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { OrganizationBasicType } from '~/types'

import { QuillMoveProjectDialog } from './QuillMoveProjectDialog'
import { QuillProjectMove } from './QuillProjectMove'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const closeModal = !projectBeingMovedLoading ? () => setIsOpen(false) : undefined
    const moveCurrentProject = currentProject ? () => moveProject(currentProject, organization.id) : undefined
    const handleConfirmationChange = (value: string): void => {
        if (currentProject) {
            setConfirmed(value.toLowerCase() === currentProject.name.toLowerCase())
        }
    }

    if (todayRailNav) {
        return (
            <QuillMoveProjectDialog
                isOpen={isOpen}
                onClose={closeModal}
                onCancel={() => setIsOpen(false)}
                projectName={currentProject?.name}
                isConfirmed={isConfirmed}
                isMoving={projectBeingMovedLoading}
                onConfirmationChange={handleConfirmationChange}
                onMove={moveCurrentProject}
            />
        )
    }

    return (
        <LemonModal
            title="Move the project to another organization?"
            onClose={closeModal}
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
                        onClick={moveCurrentProject}
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
            <LemonInput type="text" onChange={handleConfirmationChange} />
        </LemonModal>
    )
}

const NOT_ADMIN_OF_TARGET_REASON = 'You need to be an admin or owner of this organization to move a project into it'

function notAdminOfOrg(organization: OrganizationBasicType): boolean {
    return (organization.membership_level ?? OrganizationMembershipLevel.Member) < OrganizationMembershipLevel.Admin
}

export function ProjectMove(): JSX.Element {
    const { currentProject } = useValues(projectLogic)
    const { otherOrganizations } = useValues(userLogic)
    const [isModalVisible, setIsModalVisible] = useState(false)

    const [targetOrganization, setTargetOrganization] = useState<OrganizationBasicType | null>(null)

    const restrictedReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })
    const { moveProjectDisabledReason } = useValues(projectLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    // Moving a project requires admin (or owner) on BOTH organizations — the API enforces this. The source org is
    // covered by `restrictedReason` above; guard the target org here so a member of the target org gets a clear
    // message instead of a failed request.
    const targetOrgRestrictionReason =
        targetOrganization && notAdminOfOrg(targetOrganization) ? NOT_ADMIN_OF_TARGET_REASON : null

    const selectTargetOrganization = (value: string | null): void => {
        const organization = otherOrganizations.find((o) => o.id === value)
        setTargetOrganization(organization || null)
    }
    const openModal = (): void => setIsModalVisible(true)
    const selectDisabledReason = restrictedReason ?? moveProjectDisabledReason
    const moveDisabledReason =
        restrictedReason ??
        moveProjectDisabledReason ??
        (targetOrganization === null
            ? 'Please select the target organization'
            : (targetOrgRestrictionReason ?? undefined))

    if (todayRailNav) {
        return (
            <>
                <QuillProjectMove
                    projectName={currentProject?.name}
                    organizations={otherOrganizations}
                    getOrganizationDisabledReason={(o) => (notAdminOfOrg(o) ? NOT_ADMIN_OF_TARGET_REASON : undefined)}
                    targetOrganizationId={targetOrganization?.id ?? null}
                    onTargetOrganizationChange={selectTargetOrganization}
                    selectDisabledReason={selectDisabledReason}
                    onMoveClick={openModal}
                    moveDisabledReason={moveDisabledReason}
                />
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

    return (
        <>
            <p>
                Move <b>{currentProject?.name}</b> to another organization?
            </p>

            <div className="flex items-center gap-2">
                <LemonSearchableSelect
                    options={otherOrganizations.map((o) => ({
                        label: o.name,
                        value: o.id,
                        icon: <UploadedLogo size="xsmall" name={o.name} entityId={o.id} mediaId={o.logo_media_id} />,
                        disabledReason: notAdminOfOrg(o) ? NOT_ADMIN_OF_TARGET_REASON : undefined,
                    }))}
                    placeholder="Select target organization"
                    searchPlaceholder="Search organizations..."
                    searchInputDataAttr="move-project-target-organization-search"
                    noResultsMessage="No organizations match"
                    onChange={selectTargetOrganization}
                    value={targetOrganization?.id}
                    disabledReason={selectDisabledReason}
                />

                <LemonButton
                    status="danger"
                    type="secondary"
                    onClick={openModal}
                    data-attr="move-project-button"
                    icon={<IconArrowRight />}
                    disabledReason={moveDisabledReason}
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
