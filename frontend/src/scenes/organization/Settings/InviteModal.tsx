import { Alert, Button, Col, Input, Row } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'
import { userLogic } from 'scenes/userLogic'
import { PlusOutlined, CloseOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import './InviteModal.scss'
import { isEmail, pluralize } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { inviteLogic } from './inviteLogic'

/** Shuffled placeholder names */
const PLACEHOLDER_NAMES: string[] = [...Array(10).fill('Jane'), ...Array(10).fill('John'), 'Sonic'].sort(
    () => Math.random() - 0.5
)
const MAX_INVITES_AT_ONCE = 20

function InviteRow({ index, isDeletable }: { index: number; isDeletable: boolean }): JSX.Element {
    const name = PLACEHOLDER_NAMES[index % PLACEHOLDER_NAMES.length]

    const { invitesToSend } = useValues(inviteLogic)
    const { updateInviteAtIndex, inviteTeamMembers, deleteInviteAtIndex } = useActions(inviteLogic)

    return (
        <Row gutter={16} className="invite-row" align="middle">
            <Col xs={isDeletable ? 11 : 12}>
                <Input
                    placeholder={`${name.toLowerCase()}@posthog.com`}
                    type="email"
                    className={`error-on-blur${!invitesToSend[index]?.isValid ? ' errored' : ''}`}
                    onChange={(e) => {
                        const { value } = e.target
                        let isValid = true
                        if (value && !isEmail(value)) {
                            isValid = false
                        }
                        updateInviteAtIndex({ target_email: e.target.value, isValid }, index)
                    }}
                    value={invitesToSend[index]?.target_email}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            inviteTeamMembers()
                        }
                    }}
                    autoFocus={index === 0}
                />
            </Col>
            <Col xs={isDeletable ? 11 : 12}>
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
            {isDeletable && (
                <Col xs={2}>
                    <CloseOutlined style={{ color: red.primary }} onClick={() => deleteInviteAtIndex(index)} />
                </Col>
            )}
        </Row>
    )
}

export function InviteModal({ visible, onClose }: { visible: boolean; onClose: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const {
        invitesToSend,
        canSubmit,
        _invitedTeamMembersLoading: loading,
        _invitedTeamMembers,
    } = useValues(inviteLogic)
    const { appendInviteRow, resetInviteRows, inviteTeamMembers } = useActions(inviteLogic)

    useEffect(() => {
        if (_invitedTeamMembers.length) {
            onClose()
        }
    }, [_invitedTeamMembers])

    const areInvitesCreatable = invitesToSend.length + 1 < MAX_INVITES_AT_ONCE
    const areInvitesDeletable = invitesToSend.length > 1
    const validInvitesCount = invitesToSend.filter((invite) => invite.isValid && invite.target_email).length

    return (
        <Modal
            title={`Inviting team members${user?.organization ? ' to ' + user?.organization?.name : ''}`}
            visible={visible}
            onCancel={() => {
                resetInviteRows()
                onClose()
            }}
            onOk={inviteTeamMembers}
            okText={validInvitesCount ? `Invite ${pluralize(validInvitesCount, 'team member')}` : 'Invite team members'}
            destroyOnClose
            okButtonProps={{ disabled: !canSubmit, loading }}
            cancelButtonProps={{ disabled: loading }}
            closable={!loading}
        >
            {preflight?.licensed_users_available === 0 ? (
                <Alert
                    type="warning"
                    showIcon
                    message={
                        <>
                            You've hit the limit of team members you can invite to your PostHog instance given your
                            license. Please contact <a href="mailto:sales@posthog.com">sales@posthog.com</a> to upgrade
                            your license.
                        </>
                    }
                />
            ) : (
                <div className="bulk-invite-modal">
                    <p>
                        An invite is <b>specific to an email address</b> and <b>expires after 3 days</b>.
                        <br />
                        Name can be provided for the team member's convenience.
                    </p>
                    <Row gutter={16}>
                        <Col xs={areInvitesDeletable ? 11 : 12}>
                            <b>Email address</b>
                        </Col>
                        <Col xs={areInvitesDeletable ? 11 : 12}>
                            <b>
                                Name <i>(optional)</i>
                            </b>
                        </Col>
                    </Row>

                    {invitesToSend.map((_, index) => (
                        <InviteRow index={index} key={index.toString()} isDeletable={areInvitesDeletable} />
                    ))}

                    <div className="mt">
                        {areInvitesCreatable && (
                            <Button block onClick={appendInviteRow} icon={<PlusOutlined />}>
                                Add another team member
                            </Button>
                        )}
                    </div>
                </div>
            )}
            {!preflight?.email_service_available && (
                <Alert
                    type="warning"
                    style={{ marginTop: 16 }}
                    message={
                        <>
                            Sending emails is not enabled in your PostHog instance.
                            <br />
                            Remember to <b>share the invite link</b> with each team member you want to invite.
                        </>
                    }
                />
            )}
        </Modal>
    )
}
