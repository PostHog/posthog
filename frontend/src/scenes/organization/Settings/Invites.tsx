import React, { useState } from 'react'
import { Modal, Button } from 'antd'
import { useValues, useActions } from 'kea'
import { DeleteOutlined, ExclamationCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { OrganizationInviteType } from '~/types'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { inviteLogic } from './inviteLogic'
import { InviteModal } from './InviteModal'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { createdByColumn } from 'lib/components/LemonTable/columnUtils'

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

    const columns: LemonTableColumns<OrganizationInviteType> = [
        {
            title: 'Invitee',
            dataIndex: 'target_email',
            key: 'target_email',
            render: function TargetEmail(_, invite): JSX.Element | string {
                return invite.target_email ? (
                    <div className="flex-center">
                        <ProfilePicture
                            name={invite.first_name}
                            email={invite.target_email}
                            size="md"
                            style={{ marginRight: 4 }}
                        />
                        {invite.target_email}
                    </div>
                ) : (
                    <i>no one</i>
                )
            },
        },
        {
            title: 'Created At',
            dataIndex: 'created_at',
            key: 'created_at',
            render: (_, { created_at }) => humanFriendlyDetailedTime(created_at),
        },
        createdByColumn() as LemonTableColumn<OrganizationInviteType, keyof OrganizationInviteType | undefined>,
        {
            title: 'Invite Link',
            dataIndex: 'id',
            key: 'link',
            render: (_, invite) => InviteLinkComponent(invite.id, invite),
        },
        {
            title: '',
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
            <LemonTable
                dataSource={invites}
                columns={columns}
                rowKey="id"
                loading={invitesLoading}
                style={{ marginTop: '1rem' }}
                data-attr="invites-table"
                emptyState={
                    <div className="text-muted-alt text-center">
                        There are no outstanding invitations. You can invite another team member above.
                    </div>
                }
            />
            <InviteModal visible={invitingModal} onClose={() => setInvitingModal(false)} />
        </div>
    )
}
