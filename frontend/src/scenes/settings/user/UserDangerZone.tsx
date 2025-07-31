import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { detailedTime, humanFriendlyDetailedTime, isNotNil } from 'lib/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { DeleteOrganizationModal } from '../organization/OrganizationDangerZone'
import { TagList } from './PersonalAPIKeys'
import { personalAPIKeysLogic } from './personalAPIKeysLogic'
import { userDangerZoneLogic } from './userDangerZoneLogic'

const DELETE_CONFIRMATION_TEXT = 'permanently delete data'

export function DeleteUserModal({
    isOpen,
    setIsOpen,
}: {
    isOpen: boolean
    setIsOpen: (open: boolean) => void
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { push } = useActions(router)
    const { updateCurrentOrganization, deleteUser } = useActions(userLogic)
    const { userLoading } = useValues(userLogic)
    const { organizationToDelete, isUserDeletionConfirmed } = useValues(userDangerZoneLogic)
    const { leaveOrganization, setOrganizationToDelete, setIsUserDeletionConfirmed } = useActions(userDangerZoneLogic)
    const organizations = (user?.organizations ?? []).filter(isNotNil)
    const { keys } = useValues(personalAPIKeysLogic)
    const { loadKeys } = useActions(personalAPIKeysLogic)

    useEffect(() => {
        loadKeys()
    }, [loadKeys])

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
                            disabled={!isUserDeletionConfirmed}
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

                        {keys.length > 0 && (
                            <>
                                <p className="text-danger font-semibold mt-4">
                                    The following personal API keys will be deleted
                                </p>
                                <LemonTable
                                    dataSource={keys}
                                    size="small"
                                    className="mt-2"
                                    columns={[
                                        {
                                            title: 'Label',
                                            dataIndex: 'label',
                                            key: 'label',
                                            render: (label) => <span className="font-semibold">{String(label)}</span>,
                                        },
                                        {
                                            title: 'Last Used',
                                            dataIndex: 'last_used_at',
                                            key: 'lastUsedAt',
                                            render: (_, key) => {
                                                return (
                                                    <Tooltip title={detailedTime(key.last_used_at)} placement="bottom">
                                                        {humanFriendlyDetailedTime(
                                                            key.last_used_at,
                                                            'MMMM DD, YYYY',
                                                            'h A'
                                                        )}
                                                    </Tooltip>
                                                )
                                            },
                                        },
                                        {
                                            title: 'Scopes',
                                            key: 'scopes',
                                            dataIndex: 'scopes',
                                            render: (_, key) =>
                                                key.scopes[0] === '*' ? (
                                                    <LemonTag type="warning">All access</LemonTag>
                                                ) : (
                                                    <TagList tags={key.scopes} onMoreClick={() => {}} />
                                                ),
                                        },
                                    ]}
                                />
                            </>
                        )}

                        <p className="mt-4">
                            Please type <strong className="select-none">{DELETE_CONFIRMATION_TEXT}</strong> to confirm
                            account deletion.
                        </p>
                        <LemonInput
                            type="text"
                            onChange={(value) => {
                                setIsUserDeletionConfirmed(
                                    value.toLowerCase() === DELETE_CONFIRMATION_TEXT.toLowerCase()
                                )
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
    const { setDeleteUserModalOpen } = useActions(userDangerZoneLogic)
    const { deleteUserModalOpen } = useValues(userDangerZoneLogic)

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
                        onClick={() => setDeleteUserModalOpen(true)}
                        data-attr="delete-user-button"
                        icon={<IconTrash />}
                    >
                        Delete your account
                    </LemonButton>
                </div>
            </div>
            <DeleteUserModal isOpen={deleteUserModalOpen} setIsOpen={setDeleteUserModalOpen} />
        </>
    )
}
