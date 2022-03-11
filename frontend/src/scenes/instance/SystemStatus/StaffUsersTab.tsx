import { Button, Divider, Modal, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { IconClose, IconOpenInNew } from 'lib/components/icons'
import { LemonTableColumns, LemonTable } from 'lib/components/LemonTable'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import React from 'react'
import { UserType } from '~/types'
import { staffUsersLogic } from './staffUsersLogic'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'

export function StaffUsersTab(): JSX.Element {
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
                        title="Cancel the invite"
                        data-attr="invite-delete"
                        icon={<IconClose />}
                        status="danger"
                        onClick={() => {
                            Modal.confirm({
                                title: `Are you sure you want to remove ${user.first_name} as a Staff User?`,
                                icon: <ExclamationCircleOutlined />,
                                okText: 'Yes, remove',
                                okType: 'danger',
                                onOk() {
                                    deleteStaffUser(user.uuid)
                                },
                                cancelText: 'No, keep',
                            })
                        }}
                    />
                )
            },
        },
    ]

    return (
        <div>
            <div className="flex-center">
                <div style={{ flexGrow: 1 }}>
                    <h3 className="l3" style={{ marginTop: 16 }}>
                        Staff Users
                    </h3>
                    <div className="mb">
                        Users who have permissions to change instance-wide settings.{' '}
                        <a href="https://posthog.com/docs/self-host/configure/instance-settings" target="_blank">
                            Learn more <IconOpenInNew style={{ verticalAlign: 'middle' }} />
                        </a>
                        .
                    </div>
                </div>
            </div>
            <Divider style={{ margin: 0, marginBottom: 16 }} />
            <section>
                <div style={{ display: 'flex', marginBottom: '0.75rem' }}>
                    {/* TOOD: Use Lemon instead of Ant components here */}
                    <Select
                        mode="multiple"
                        placeholder="Add staff users here…"
                        loading={allUsersLoading}
                        value={staffUsersToBeAdded}
                        onChange={(newValues) => setStaffUsersToBeAdded(newValues)}
                        showArrow
                        showSearch
                        style={{ flexGrow: 1 }}
                    >
                        {nonStaffUsers.map((user) => (
                            <Select.Option
                                key={user.uuid}
                                value={user.uuid}
                                title={`${user.first_name} (${user.email})`}
                            >
                                <ProfilePicture
                                    name={user.first_name}
                                    email={user.email}
                                    size="sm"
                                    style={{ display: 'inline-flex', marginRight: 8 }}
                                />
                                {user.first_name} ({user.email})
                            </Select.Option>
                        ))}
                    </Select>
                    <Button
                        type="primary"
                        style={{ flexShrink: 0, marginLeft: '0.5rem' }}
                        loading={allUsersLoading}
                        disabled={staffUsersToBeAdded.length === 0}
                        onClick={addStaffUsers}
                    >
                        Add
                    </Button>
                </div>
            </section>
            <LemonTable dataSource={staffUsers} columns={columns} loading={allUsersLoading} rowKey="uuid" />
        </div>
    )
}
