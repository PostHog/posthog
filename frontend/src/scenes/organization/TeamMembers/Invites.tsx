import React from 'react'
import { Table, Modal, Divider } from 'antd'
import { useValues, useActions } from 'kea'
import { invitesLogic } from './invitesLogic'
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { hot } from 'react-hot-loader/root'
import { OrganizationInviteType, UserNestedType } from '~/types'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { CreateInviteModalWithButton } from './CreateInviteModal'
import { ColumnsType } from 'antd/lib/table'

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
export const Invites = hot(_Invites)
function _Invites(): JSX.Element {
    const { invites, invitesLoading } = useValues(invitesLogic)
    const { deleteInvite } = useActions(invitesLogic)

    const columns: ColumnsType = [
        {
            title: 'Target Email',
            dataIndex: 'target_email',
            key: 'target_email',
            render: function TargetEmail(target_email: string | null): JSX.Element | string {
                return target_email ?? <i>none</i>
            },
        },
        {
            title: 'Created At',
            dataIndex: 'created_at',
            key: 'created_at',
            render: (created_at: string) => humanFriendlyDetailedTime(created_at),
        },
        {
            title: 'Created By',
            dataIndex: 'created_by',
            key: 'created_by',
            render: (createdBy?: UserNestedType) => (createdBy ? `${createdBy.first_name} (${createdBy.email})` : '–'),
        },
        {
            title: 'Invite Link',
            dataIndex: 'id',
            key: 'link',
            render: (id, invite) => InviteLinkComponent(id as string, invite as OrganizationInviteType),
        },
        {
            title: '',
            dataIndex: 'actions',
            key: 'actions',
            render: makeActionsComponent(deleteInvite),
        },
    ]

    return invites.length ? (
        <>
            <h2 className="subtitle" style={{ justifyContent: 'space-between' }}>
                Pending Organization Invites
                <CreateInviteModalWithButton />
            </h2>
            <Table
                dataSource={invites}
                columns={columns}
                rowKey="id"
                pagination={false}
                loading={invitesLoading}
                style={{ marginTop: '1rem' }}
            />
            <Divider />
        </>
    ) : (
        <div className="text-right">
            <CreateInviteModalWithButton />
        </div>
    )
}
