import { useActions, useValues } from 'kea'
import { Dispatch, SetStateAction, useEffect, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import type { OrganizationBasicType } from '~/types'

export function DeleteOrganizationModal({
    isOpen,
    setIsOpen,
    organization,
    redirectPath,
}: {
    organization: OrganizationBasicType | null
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
    redirectPath?: string
}): JSX.Element | null {
    const { organizationBeingDeleted } = useValues(organizationLogic)
    const { deleteOrganization } = useActions(organizationLogic)

    const [confirmationText, setConfirmationText] = useState('')
    const isDeletionInProgress = !!organization && organizationBeingDeleted === organization.id
    const isDeletionConfirmed = !!organization && confirmationText.toLowerCase() === organization.name.toLowerCase()

    // Reset stale confirmation state left over from a previous open of this modal.
    useEffect(() => {
        if (isOpen) {
            setConfirmationText('')
        }
    }, [isOpen])

    return (
        <LemonModal
            title="Delete the entire organization?"
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
                        status="danger"
                        disabledReason={!isDeletionConfirmed ? 'Type the organization name to confirm' : undefined}
                        loading={isDeletionInProgress}
                        data-attr="delete-organization-ok"
                        onClick={
                            organization
                                ? () => deleteOrganization({ organizationId: organization.id, redirectPath })
                                : undefined
                        }
                    >{`Delete ${organization ? organization.name : 'the current organization'}`}</LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                Organization deletion <b>cannot be undone</b>. You will lose all data, <b>including all events</b>,
                related to all projects within this organization.
            </p>
            <p>
                Please type <strong>{organization ? organization.name : "this organization's name"}</strong> to confirm.
            </p>
            <LemonInput
                type="text"
                value={confirmationText}
                onChange={setConfirmationText}
                data-attr="delete-organization-confirmation-input"
            />
        </LemonModal>
    )
}

export function OrganizationDangerZone(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const [isModalVisible, setIsModalVisible] = useState(false)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Owner,
        scope: RestrictionScope.Organization,
    })

    return (
        <>
            <div className="text-danger">
                {!restrictionReason && (
                    <p className="text-danger">
                        This is <b>irreversible</b>. Please be certain.
                    </p>
                )}
                <LemonButton
                    status="danger"
                    type="secondary"
                    onClick={() => setIsModalVisible(true)}
                    data-attr="delete-organization-button"
                    icon={<IconTrash />}
                    disabledReason={restrictionReason}
                >
                    Delete {currentOrganization?.name || 'the current organization'}
                </LemonButton>
            </div>
            {currentOrganization && (
                <DeleteOrganizationModal
                    isOpen={isModalVisible}
                    setIsOpen={setIsModalVisible}
                    organization={currentOrganization}
                    redirectPath={urls.default()}
                />
            )}
        </>
    )
}
