import React, { useCallback } from 'react'
import { Table, Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { invitesLogic } from './logic'
import { CreateOrgInviteModalWithButton } from './CreateOrgInviteModal'
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { hot } from 'react-hot-loader/root'
import { UserType } from '~/types'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export const Invites = hot(_Invites)
function _Invites({ user }: { user: UserType }): JSX.Element {
    const { invites, invitesLoading } = useValues(invitesLogic)
    const { deleteInvite } = useActions(invitesLogic)
    const { confirm } = Modal

    const ActionsComponent = useCallback(
        (_text, invite) => {
            function handleClick(): void {
                confirm({
                    title: `Delete invite?`,
                    icon: <ExclamationCircleOutlined />,
                    okText: 'Delete',
                    okType: 'danger',
                    cancelText: 'Cancel',
                    onOk() {
                        deleteInvite(invite)
                    },
                })
            }

            return (
                <div>
                    <a className="text-danger" onClick={handleClick}>
                        <DeleteOutlined />
                    </a>
                </div>
            )
        },
        [user]
    )

    const columns = [
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
            key: 'created_by',
            render: (createdAt: string) => humanFriendlyDetailedTime(createdAt),
        },
        {
            title: 'Created By',
            dataIndex: 'created_by_first_name',
            key: 'created_by',
            render: (createdByFirstName: string, invite: Record<string, any>) =>
                `${createdByFirstName} (${invite.created_by_email})`,
        },
        {
            title: 'Link',
            dataIndex: 'id',
            key: 'link',
            render: function InviteLink(id: string): JSX.Element {
                const url = new URL(`/signup/${id}`, document.baseURI).href
                return (
                    <CopyToClipboardInline data-attr="invite-link" description="invite URL">
                        {url}
                    </CopyToClipboardInline>
                )
            },
        },
        {
            title: '',
            dataIndex: 'actions',
            key: 'actions',
            align: 'center',
            render: ActionsComponent,
        },
    ]

    return (
        <>
            <h1 className="page-header">Organization Invites – {user.organization.name}</h1>
            <div style={{ maxWidth: 672 }}>
                <i>
                    <p>Create, send out, and delete organization invites.</p>
                </i>
            </div>
            <CreateOrgInviteModalWithButton />
            <Table
                dataSource={invites}
                columns={columns}
                rowKey="id"
                pagination={false}
                loading={invitesLoading}
                style={{ marginTop: '1rem' }}
            />
        </>
    )
}
