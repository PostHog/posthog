import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { isNotNil } from 'lib/utils'
import { Dispatch, SetStateAction, useState } from 'react'
import { userLogic } from 'scenes/userLogic'

const DELETE_CONFIRMATION_TEXT = 'permanently delete account'

export function DeleteUserModal({
    isOpen,
    setIsOpen,
}: {
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { deleteUser } = useActions(userLogic)

    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const isDeletionInProgress = false

    const organizations = (user?.organizations ?? []).filter(isNotNil)

    const ownedOrganizations = organizations.filter(
        (organization) => organization.membership_level === OrganizationMembershipLevel.Owner
    )

    return (
        <LemonModal
            title="Delete your account"
            onClose={!isDeletionInProgress ? () => setIsOpen(false) : undefined}
            footer={
                <>
                    <LemonButton
                        disabledReason={isDeletionInProgress && 'Processing...'}
                        type="secondary"
                        onClick={() => setIsOpen(false)}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        disabled={!isDeletionConfirmed}
                        loading={isDeletionInProgress}
                        data-attr="delete-user-ok"
                        status="danger"
                        onClick={() => deleteUser()}
                    >
                        Delete account
                    </LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                Account deletion <b>cannot be undone</b>. You will lose all your data permanently.
            </p>
            <p>The following organizations will be deleted:</p>
            {ownedOrganizations.length > 0 && (
                <>
                    <LemonTable
                        dataSource={ownedOrganizations}
                        size="small"
                        columns={[
                            {
                                title: 'Organization',
                                render: function RenderOrganizationName(_, organization) {
                                    return <div className="text-md font-semibold">{organization.name}</div>
                                },
                            },
                            {
                                title: '',
                                render: function RenderActionButton(_, organization) {
                                    return (
                                        <div className="flex justify-end py-1 text-danger font-semibold">
                                            {organization.membership_level === OrganizationMembershipLevel.Owner
                                                ? 'Will be deleted'
                                                : 'Leave'}
                                        </div>
                                    )
                                },
                            },
                        ]}
                    />
                </>
            )}

            <p className="pt-4">
                Please type <strong>{DELETE_CONFIRMATION_TEXT}</strong> to confirm account deletion.
            </p>
            <LemonInput
                type="text"
                onChange={(value) => {
                    setIsDeletionConfirmed(value.toLowerCase() === DELETE_CONFIRMATION_TEXT.toLowerCase())
                }}
            />
        </LemonModal>
    )
}

export function UserDangerZone(): JSX.Element {
    const [isModalVisible, setIsModalVisible] = useState(false)

    return (
        <>
            <div className="text-danger">
                <div className="mt-4">
                    <p className="text-danger">
                        This is <b>irreversible</b>. Please be certain.
                    </p>
                    <LemonButton
                        status="danger"
                        type="secondary"
                        onClick={() => setIsModalVisible(true)}
                        data-attr="delete-user-button"
                        icon={<IconTrash />}
                    >
                        Delete your account
                    </LemonButton>
                </div>
            </div>
            <DeleteUserModal isOpen={isModalVisible} setIsOpen={setIsModalVisible} />
        </>
    )
}
