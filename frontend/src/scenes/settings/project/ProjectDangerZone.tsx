import { useActions, useValues } from 'kea'
import { Dispatch, SetStateAction, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

/**
 * Usage limits are organization-scoped, so people who hit one often delete or recreate a project
 * expecting ingestion to resume. Say here that it will not, and name the steps that do work.
 */
function UsageLimitDeletionNotice(): JSX.Element | null {
    const { productsAtOrOverUsageLimit } = useValues(billingLogic)

    if (productsAtOrOverUsageLimit.length === 0) {
        return null
    }
    const isErrorTrackingLimited = productsAtOrOverUsageLimit.some((product) => product.type === 'error_tracking')

    return (
        <p className="mt-2 p-2 bg-bg-3000 rounded text-sm">
            <strong>Your organization has reached a usage limit.</strong> Usage counts across the whole organization, so
            a new project shares the same limit and deleting this one does not give the usage back. To start ingesting
            again, <Link to={urls.organizationBilling()}>raise or remove the limit</Link>
            {isErrorTrackingLimited && (
                <>
                    , then add a{' '}
                    <Link
                        to={urls.settings(
                            'environment-error-tracking-configuration',
                            'error-tracking-suppression-rules'
                        )}
                    >
                        suppression rule
                    </Link>{' '}
                    so the same errors cannot use the allowance again
                </>
            )}
            .
        </p>
    )
}

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
            <UsageLimitDeletionNotice />
            <p>
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
                        Delete {currentProject?.name || 'the current project'}
                    </LemonButton>
                </div>
            </div>
            <DeleteProjectModal isOpen={isModalVisible} setIsOpen={setIsModalVisible} />
        </>
    )
}
