import React from 'react'
import { Modal } from 'antd'
import { useValues, useActions } from 'kea'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { OrganizationInviteType } from '~/types'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { inviteLogic } from './inviteLogic'
import { EmailUnavailableMessage } from './InviteModal'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'

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
            <LemonButton
                title="Cancel the invite"
                data-attr="invite-delete"
                icon={<IconClose />}
                status="danger"
                onClick={() => {
                    invite.is_expired
                        ? deleteInvite(invite)
                        : Modal.confirm({
                              title: `Do you want to cancel the invite for ${invite.target_email}?`,
                              icon: <ExclamationCircleOutlined />,
                              okText: 'Yes, cancel invite',
                              okType: 'danger',
                              onOk() {
                                  deleteInvite(invite)
                              },
                              cancelText: 'No, keep invite',
                          })
                }}
            />
        )
    }
}
export function Invites(): JSX.Element {
    const { invites, invitesLoading } = useValues(inviteLogic)
    const { deleteInvite, showInviteModal } = useActions(inviteLogic)
    const { preflight } = useValues(preflightLogic)

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
                            style={{ marginRight: 8 }}
                        />
                        {invite.target_email}
                        {invite.first_name ? ` (${invite.first_name})` : ''}
                    </div>
                ) : (
                    <i>no one</i>
                )
            },
            width: '20%',
        },
        createdByColumn() as LemonTableColumn<OrganizationInviteType, keyof OrganizationInviteType | undefined>,
        createdAtColumn() as LemonTableColumn<OrganizationInviteType, keyof OrganizationInviteType | undefined>,
        {
            title: 'Invite Link',
            dataIndex: 'id',
            key: 'link',
            render: (_, invite) => InviteLinkComponent(invite.id, invite),
        },
        {
            title: '',
            key: 'actions',
            width: 24,
            render: makeActionsComponent(deleteInvite),
        },
    ]

    return (
        <div>
            <h2 id="invites" className="subtitle" style={{ justifyContent: 'space-between' }}>
                Pending Invites
                <LemonButton type="primary" onClick={showInviteModal} data-attr="invite-teammate-button">
                    Invite team member
                </LemonButton>
            </h2>
            {!preflight?.email_service_available && <EmailUnavailableMessage />}
            <LemonTable
                dataSource={invites}
                columns={columns}
                rowKey="id"
                loading={invitesLoading}
                style={{ marginTop: '1rem' }}
                data-attr="invites-table"
                emptyState="There are no outstanding invitations. You can invite another team member above."
            />
        </div>
    )
}
