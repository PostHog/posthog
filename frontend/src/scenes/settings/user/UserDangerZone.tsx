import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { OrganizationMembershipLevel } from 'lib/constants'
import { isNotNil } from 'lib/utils'
import { Dispatch, SetStateAction, useEffect, useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { OrganizationBasicType } from '~/types'

import { DeleteOrganizationModal } from '../organization/OrganizationDangerZone'

const DELETE_CONFIRMATION_TEXT = 'permanently delete data'

export function DeleteUserModal({
    isOpen,
    setIsOpen,
}: {
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const { updateCurrentOrganization } = useActions(userLogic)
    const { deleteUser, userLoading } = useActions(userLogic)
    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const [organizationToDelete, setOrganizationToDelete] = useState<OrganizationBasicType | null>(null)
    const organizations = (user?.organizations ?? []).filter(isNotNil)

    useEffect(() => {
        if ((searchParams.organizationDeleted || searchParams.deletingUser) && !isOpen) {
            setIsOpen(true)
            router.actions.push(urls.settings('user-danger-zone'))
        }
    }, [searchParams?.organizationDeleted, searchParams?.deletingUser, isOpen, setIsOpen])

    return (
        <>
            <LemonModal
                title="Delete your account"
                onClose={!userLoading ? () => setIsOpen(false) : undefined}
                footer={
                    <>
                        <LemonButton
                            disabledReason={userLoading && 'Loading...'}
                            type="secondary"
                            onClick={() => setIsOpen(false)}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            disabled={!isDeletionConfirmed}
                            loading={userLoading}
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
                {organizations.length > 0 && (
                    <>
                        <p className="text-danger font-semibold">
                            You must leave or delete all organizations before deleting your account.
                        </p>
                        <LemonTable
                            dataSource={organizations}
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
                                            <div className="flex justify-end items-center gap-2 py-1 text-danger font-semibold">
                                                {organization.membership_level ===
                                                    OrganizationMembershipLevel.Owner && (
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        status="default"
                                                        onClick={() => {
                                                            if (organization.id === user?.organization?.id) {
                                                                push(urls.settings('organization-members'))
                                                            } else {
                                                                updateCurrentOrganization(
                                                                    organization.id,
                                                                    urls.settings('organization-members')
                                                                )
                                                            }
                                                        }}
                                                    >
                                                        Transfer ownership
                                                    </LemonButton>
                                                )}
                                                {organization.membership_level !==
                                                    OrganizationMembershipLevel.Owner && (
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        status="default"
                                                        onClick={() => {
                                                            LemonDialog.open({
                                                                title: `Leave organization ${organization.name}?`,
                                                                primaryButton: {
                                                                    children: 'Leave',
                                                                    status: 'danger',
                                                                    onClick: () => leaveOrganization(organization.id),
                                                                },
                                                                secondaryButton: {
                                                                    children: 'Cancel',
                                                                },
                                                            })
                                                        }}
                                                    >
                                                        Leave organization
                                                    </LemonButton>
                                                )}
                                                {organization.membership_level ===
                                                    OrganizationMembershipLevel.Owner && (
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        status="danger"
                                                        onClick={() => {
                                                            setOrganizationToDelete(organization)
                                                        }}
                                                    >
                                                        Delete organization
                                                    </LemonButton>
                                                )}
                                            </div>
                                        )
                                    },
                                },
                            ]}
                        />
                    </>
                )}
                {organizations.length === 0 && (
                    <>
                        <p>
                            Account deletion <b>cannot be undone</b>. You will lose all your data permanently.
                        </p>
                        <p>
                            Please type <strong className="select-none">{DELETE_CONFIRMATION_TEXT}</strong> to confirm
                            account deletion.
                        </p>
                        <LemonInput
                            type="text"
                            onChange={(value) => {
                                setIsDeletionConfirmed(value.toLowerCase() === DELETE_CONFIRMATION_TEXT.toLowerCase())
                            }}
                        />
                    </>
                )}
            </LemonModal>
            <DeleteOrganizationModal
                isOpen={organizationToDelete !== null}
                setIsOpen={() => setOrganizationToDelete(null)}
                organization={organizationToDelete}
            />
        </>
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
