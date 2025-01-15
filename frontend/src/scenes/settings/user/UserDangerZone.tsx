import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { isNotNil } from 'lib/utils'
import { Dispatch, SetStateAction, useState } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

export function RemoveFromOrganizationsModal({
    isOpen,
    setIsOpen,
}: {
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { otherOrganizations, user } = useValues(userLogic)
    const { removeMember } = useActions(membersLogic)
    const { deleteOrganization } = useActions(organizationLogic)

    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const isDeletionInProgress = false

    const organizations = [currentOrganization, ...otherOrganizations].filter(isNotNil)

    return (
        <LemonModal
            title="Remove yourself from organizations"
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
                        disabled={!isDeletionConfirmed || organizations.length > 0}
                        loading={isDeletionInProgress}
                        data-attr="delete-user-ok"
                        status="danger"
                        onClick={() => {
                            // Add logic to delete user account
                        }}
                    >
                        Delete account
                    </LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            {organizations.length > 0 ? (
                <>
                    <p>You must leave or delete all organizations before you can delete your account.</p>
                    <LemonTable
                        dataSource={organizations.filter(isNotNil)}
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
                                        <div className="flex justify-end py-1">
                                            <LemonButton
                                                type="secondary"
                                                onClick={() =>
                                                    organization.membership_level === OrganizationMembershipLevel.Owner
                                                        ? deleteOrganization(organization)
                                                        : removeMember({ user })
                                                }
                                            >
                                                {organization.membership_level === OrganizationMembershipLevel.Owner
                                                    ? 'Delete'
                                                    : 'Leave'}
                                            </LemonButton>
                                        </div>
                                    )
                                },
                            },
                        ]}
                    />
                </>
            ) : (
                <>
                    <p>
                        Account deletion <b>cannot be undone</b>. You will lose all your data.
                    </p>
                    <p>
                        Please type <strong>delete me</strong> to confirm account deletion.
                    </p>
                    <LemonInput
                        type="text"
                        onChange={(value) => {
                            setIsDeletionConfirmed(value.toLowerCase() === 'delete me'.toLowerCase())
                        }}
                    />
                </>
            )}
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
            <RemoveFromOrganizationsModal isOpen={isModalVisible} setIsOpen={setIsModalVisible} />
        </>
    )
}
