import React, { useState } from 'react'
import { Table, Modal, Button } from 'antd'
import { useValues, useActions } from 'kea'
import { DeleteOutlined, ExclamationCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { OrganizationInviteType, UserBasicType } from '~/types'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ColumnsType } from 'antd/lib/table'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { inviteLogic } from './inviteLogic'
import { InviteModal } from './InviteModal'

function InviteLinkComponent(id: string, invite: OrganizationInviteType): JSX.Element {
    const url = new URL(`/signup/${id}`, document.baseURI).href
    return invite.is_expired ? (
        <b>Expired! Delete and recreate</b>
    ) : (
        <CopyToClipboardInline data-attr="invite-link" description="invite link">
            {url}
        </CopyToClipboardInline>
    )
}

function makeActionsComponent(
    deleteInvite: (invite: OrganizationInviteType) => void
): (_: any, invite: any) => JSX.Element {
    return function ActionsComponent(_, invite: OrganizationInviteType): JSX.Element {
        return (
            <DeleteOutlined
                className="text-danger"
                onClick={() => {
                    invite.is_expired
                        ? deleteInvite(invite)
                        : Modal.confirm({
                              title: `Delete invite for ${invite.target_email}?`,
                              icon: <ExclamationCircleOutlined />,
                              okText: 'Delete',
                              okType: 'danger',
                              onOk() {
                                  deleteInvite(invite)
                              },
                          })
                }}
            />
        )
    }
}
export function Invites(): JSX.Element {
    const { invites, invitesLoading } = useValues(inviteLogic)
    const { deleteInvite } = useActions(inviteLogic)
    const [invitingModal, setInvitingModal] = useState(false)

    const columns: ColumnsType<OrganizationInviteType> = [
        {
            dataIndex: 'target_email',
            key: 'target_email',
            render: function ProfilePictureRender(_, invite) {
                return <ProfilePicture name={invite.first_name} email={invite.target_email} />
            },
            width: 32,
        },
        {
            title: 'Target Email',
            dataIndex: 'target_email',
            key: 'target_email',
            render: function TargetEmail(target_email: string | null): JSX.Element | string {
                return target_email ?? <i>none</i>
            },
        },
        {
            title: 'Created At',
            dataIndex: 'created_at',
            key: 'created_at',
            render: (created_at: string) => humanFriendlyDetailedTime(created_at),
        },
        {
            title: 'Created By',
            dataIndex: 'created_by',
            key: 'created_by',
            render: (createdBy?: UserBasicType) => (createdBy ? `${createdBy.first_name} (${createdBy.email})` : '–'),
        },
        {
            title: 'Invite Link',
            dataIndex: 'id',
            key: 'link',
            render: (id, invite) => InviteLinkComponent(id as string, invite),
        },
        {
            title: '',
            dataIndex: 'actions',
            key: 'actions',
            render: makeActionsComponent(deleteInvite),
        },
    ]

    return (
        <div>
            <h2 className="subtitle" style={{ justifyContent: 'space-between' }}>
                Team invites
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setInvitingModal(true)}>
                    Invite team member
                </Button>
            </h2>
            <Table
                dataSource={invites}
                columns={columns}
                rowKey="id"
                pagination={false}
                loading={invitesLoading}
                style={{ marginTop: '1rem' }}
                data-attr="invites-table"
                locale={{
                    emptyText: function InvitesCTA() {
                        return (
                            <span className="text-muted-alt">
                                There are no outstanding invitations. You can invite another team member above.
                            </span>
                        )
                    },
                }}
            />
            <InviteModal visible={invitingModal} onClose={() => setInvitingModal(false)} />
        </div>
    )
}
