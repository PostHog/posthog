import { Button, Modal } from 'antd'
import { useValues } from 'kea'
import { IconClose, IconOpenInNew } from 'lib/components/icons'
import { LemonTableColumns, LemonTable } from 'lib/components/LemonTable'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import React from 'react'
import { UserType } from '~/types'
import { staffUsersLogic } from './staffUsersLogic'
import { PlusOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'

export function StaffUsersTab(): JSX.Element {
    const { staffUsers, staffUsersLoading } = useValues(staffUsersLogic)

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
                                    console.log('deleted')
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
                <div>
                    <Button icon={<PlusOutlined />} type="primary">
                        Add Staff User
                    </Button>
                </div>
            </div>
            <LemonTable dataSource={staffUsers} columns={columns} loading={staffUsersLoading} rowKey="uuid" />
        </div>
    )
}
