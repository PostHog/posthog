import { Divider, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import { IconDelete, IconOpenInNew } from 'lib/components/icons'
import { LemonTableColumns, LemonTable } from 'lib/components/LemonTable'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import React from 'react'
import { UserType } from '~/types'
import { staffUsersLogic } from './staffUsersLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { userLogic } from 'scenes/userLogic'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import {
    LemonSelectWithSearch,
    usersLemonSelectOptions,
} from 'lib/components/LemonSelectWithSearch/LemonSelectWithSearch'

export function StaffUsersTab(): JSX.Element {
    const { user: myself } = useValues(userLogic)
    const { staffUsers, allUsersLoading, nonStaffUsers, staffUsersToBeAdded } = useValues(staffUsersLogic)
    const { setStaffUsersToBeAdded, addStaffUsers, deleteStaffUser } = useActions(staffUsersLogic)

    const columns: LemonTableColumns<UserType> = [
        {
            key: 'profile_picture',
            render: function ProfilePictureRender(_, user) {
                return <ProfilePicture name={user.first_name} email={user.email} />
            },
            width: 32,
        },
        {
            key: 'name',
            title: 'Name',
            dataIndex: 'first_name',
            render: function ProfilePictureRender(_, user) {
                return (
                    <>
                        {user.first_name}
                        {user.uuid === myself?.uuid && <LemonTag style={{ marginLeft: 4 }}>Me</LemonTag>}
                    </>
                )
            },
        },
        {
            key: 'email',
            title: 'Email',
            dataIndex: 'email',
        },
        {
            key: 'actions',
            width: 32,
            render: function RenderActions(_, user) {
                return (
                    <LemonButton
                        data-attr="invite-delete"
                        icon={<IconDelete />}
                        status="danger"
                        disabled={staffUsers.length < 2}
                        title={
                            staffUsers.length < 2
                                ? 'You should always have at least one staff user.'
                                : 'Cancel the invite'
                        }
                        onClick={() => {
                            Modal.confirm({
                                title: `Remove ${
                                    myself?.uuid === user.uuid ? 'yourself' : user.first_name
                                } as a Staff User?`,
                                icon: null,
                                okText: 'Remove user',
                                okType: 'primary',
                                okButtonProps: { className: 'btn-danger' },
                                content: (
                                    <div style={{ border: '' }}>
                                        {myself?.uuid === user.uuid ? (
                                            <>
                                                Please confirm you want to <b>remove yourself</b> as a staff user.
                                                <div
                                                    style={{
                                                        fontWeight: 'normal',
                                                        color: 'var(--muted-alt)',
                                                    }}
                                                >
                                                    Only another staff user will be able to add you again.
                                                </div>
                                            </>
                                        ) : (
                                            `Are you sure you want to remove ${user.first_name} as a Staff User?`
                                        )}
                                    </div>
                                ),
                                onOk() {
                                    deleteStaffUser(user.uuid)
                                },
                                cancelText: 'Cancel',
                            })
                        }}
                    />
                )
            },
        },
    ]

    return (
        <div>
            <h3 className="l3" style={{ marginTop: 16 }}>
                Staff Users
            </h3>
            <div className="mb">
                Users who have permissions to manage instance-wide settings. Staff user permissions are set at the{' '}
                <b>instance-level and are independent of any organization or project permissions.</b>{' '}
                <a href="https://posthog.com/docs/self-host/configure/instance-settings#staff-users" target="_blank">
                    Learn more <IconOpenInNew style={{ verticalAlign: 'middle' }} />
                </a>
                .
            </div>
            <Divider style={{ margin: 0, marginBottom: 16 }} />
            <section>
                <div className="flex gap-05">
                    <div style={{ flex: 1 }}>
                        <LemonSelectWithSearch
                            placeholder="Add staff users here…"
                            loading={allUsersLoading}
                            value={staffUsersToBeAdded}
                            onChange={(newValues) => setStaffUsersToBeAdded(newValues)}
                            filterOption={false}
                            mode="multiple"
                            data-attr="subscribed-emails"
                            options={usersLemonSelectOptions(nonStaffUsers)}
                        />
                    </div>
                    <LemonButton
                        type="primary"
                        loading={allUsersLoading}
                        disabled={staffUsersToBeAdded.length === 0}
                        onClick={addStaffUsers}
                    >
                        Add
                    </LemonButton>
                </div>
            </section>
            <LemonTable dataSource={staffUsers} columns={columns} loading={allUsersLoading} rowKey="uuid" />
        </div>
    )
}
