import { Alert, Button, Col, Input, Row } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'
import { userLogic } from 'scenes/userLogic'
import { PlusOutlined, CloseOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import './BulkInviteModal.scss'
import { isEmail, pluralize } from 'lib/utils'
import { bulkInviteLogic } from './bulkInviteLogic'

// Placeholder names in random proportions
const PLACEHOLDER_NAMES: string[] = [...Array(10).fill('Jane'), ...Array(10).fill('John'), 'Sonic'].sort(
    () => Math.random() - 0.5
)
const MAX_INVITES_AT_ONCE = 20

function InviteRow({ index, isDeletable }: { index: number; isDeletable: boolean }): JSX.Element {
    const name = PLACEHOLDER_NAMES[index % PLACEHOLDER_NAMES.length]

    const { invites } = useValues(bulkInviteLogic)
    const { updateInviteAtIndex, inviteTeamMembers, deleteInviteAtIndex } = useActions(bulkInviteLogic)

    return (
        <Row gutter={16} className="invite-row" align="middle">
            <Col xs={11}>
                <Input
                    placeholder={`${name.toLowerCase()}@posthog.com`}
                    type="email"
                    className={`error-on-blur${!invites[index]?.isValid ? ' errored' : ''}`}
                    onChange={(e) => {
                        const { value } = e.target
                        let isValid = true
                        if (value && !isEmail(value)) {
                            isValid = false
                        }
                        updateInviteAtIndex({ target_email: e.target.value, isValid }, index)
                    }}
                    value={invites[index]?.target_email}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            inviteTeamMembers()
                        }
                    }}
                />
            </Col>
            <Col xs={11}>
                <Input
                    placeholder={name}
                    onChange={(e) => {
                        updateInviteAtIndex({ first_name: e.target.value }, index)
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            inviteTeamMembers()
                        }
                    }}
                />
            </Col>
            <Col xs={1}>
                <CloseOutlined
                    style={isDeletable ? { color: red.primary } : { opacity: 0.5 }}
                    onClick={isDeletable ? () => deleteInviteAtIndex(index) : undefined}
                />
            </Col>
        </Row>
    )
}

export function BulkInviteModal({ visible, onClose }: { visible: boolean; onClose: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const { invites, canSubmit, invitedTeamMembersLoading, invitedTeamMembers } = useValues(bulkInviteLogic)
    const { appendInviteRow, resetInviteRows, inviteTeamMembers } = useActions(bulkInviteLogic)

    useEffect(() => {
        if (invitedTeamMembers.length) {
            onClose()
        }
    }, [invitedTeamMembers])

    return (
        <Modal
            title={`Inviting team members${user?.organization ? ' to ' + user?.organization?.name : ''}`}
            visible={visible}
            onCancel={() => {
                resetInviteRows()
                onClose()
            }}
            onOk={inviteTeamMembers}
            okText={`Invite ${pluralize(
                invites.filter((invite) => invite.isValid && invite.target_email).length,
                'team member'
            )}`}
            destroyOnClose
            okButtonProps={{ disabled: !canSubmit, loading: invitedTeamMembersLoading }}
            cancelButtonProps={{ disabled: invitedTeamMembersLoading }}
            closable={!invitedTeamMembersLoading}
        >
            <div className="bulk-invite-modal">
                <p>
                    An invite is <b>specific to an email address</b> and <b>expires after 3 days</b>.
                    <br />
                    Name can optionally be provided for the invitee's convenience.
                </p>
                <Row gutter={16}>
                    <Col xs={11}>
                        <b>
                            Email address <i>(required)</i>
                        </b>
                    </Col>
                    <Col xs={11}>
                        <b>
                            Name <i>(optional)</i>
                        </b>
                    </Col>
                </Row>

                {invites.map((_, index) => (
                    <InviteRow index={index} key={index.toString()} isDeletable={invites.length > 1} />
                ))}

                <div className="mt">
                    <Button
                        block
                        className="btn-add"
                        onClick={appendInviteRow}
                        disabled={invites.length + 1 >= MAX_INVITES_AT_ONCE}
                    >
                        <PlusOutlined /> Add another team member
                    </Button>
                </div>
            </div>
            {!user?.email_service_available && (
                <Alert
                    type="warning"
                    style={{ marginTop: 16 }}
                    message={
                        <>
                            Sending emails is not enabled in your PostHog instance.
                            <br />
                            Remember to <b>share the invite link</b> with the team member you want to invite.
                        </>
                    }
                />
            )}
        </Modal>
    )
}
