import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IconDelete } from 'lib/lemon-ui/icons'
import { Dispatch, SetStateAction, useState } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'

export function DeleteOrganizationModal({
    isOpen,
    setIsOpen,
}: {
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { currentOrganization, organizationBeingDeleted } = useValues(organizationLogic)
    const { deleteOrganization } = useActions(organizationLogic)

    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const isDeletionInProgress = !!currentOrganization && organizationBeingDeleted?.id === currentOrganization.id

    return (
        <LemonModal
            title="Delete the entire organization?"
            onClose={!isDeletionInProgress ? () => setIsOpen(false) : undefined}
            footer={
                <>
                    <LemonButton disabled={isDeletionInProgress} type="secondary" onClick={() => setIsOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabled={!isDeletionConfirmed}
                        loading={isDeletionInProgress}
                        data-attr="delete-organization-ok"
                        status="danger"
                        onClick={currentOrganization ? () => deleteOrganization(currentOrganization) : undefined}
                    >{`Delete ${
                        currentOrganization ? currentOrganization.name : 'the current organization'
                    }`}</LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                Organization deletion <b>cannot be undone</b>. You will lose all data, <b>including all events</b>,
                related to all projects within this organization.
            </p>
            <p>
                Please type{' '}
                <strong>{currentOrganization ? currentOrganization.name : "this organization's name"}</strong> to
                confirm.
            </p>
            <LemonInput
                type="text"
                onChange={(value) => {
                    if (currentOrganization) {
                        setIsDeletionConfirmed(value.toLowerCase() === currentOrganization.name.toLowerCase())
                    }
                }}
            />
        </LemonModal>
    )
}

export function OrganizationDangerZone(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const [isModalVisible, setIsModalVisible] = useState(false)
    const isRestricted = !!useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <>
            <div className="text-danger">
                {!isRestricted && (
                    <p className="text-danger">
                        This is <b>irreversible</b>. Please be certain.
                    </p>
                )}
                <LemonButton
                    status="danger"
                    type="secondary"
                    onClick={() => setIsModalVisible(true)}
                    data-attr="delete-organization-button"
                    icon={<IconDelete />}
                    disabled={isRestricted}
                >
                    Delete {currentOrganization?.name || 'the current organization'}
                </LemonButton>
            </div>
            <DeleteOrganizationModal isOpen={isModalVisible} setIsOpen={setIsModalVisible} />
        </>
    )
}
