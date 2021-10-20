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
import { preflightLogic } from 'scenes/PreflightCheck/logic'

/** Shuffled placeholder names */
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
            <Col xs={isDeletable ? 11 : 12}>
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

export function BulkInviteModal({ visible, onClose }: { visible: boolean; onClose: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { invites, canSubmit, invitedTeamMembersLoading, invitedTeamMembers } = useValues(bulkInviteLogic)
    const { appendInviteRow, resetInviteRows, inviteTeamMembers } = useActions(bulkInviteLogic)

    useEffect(
        () => {
            if (invitedTeamMembers.length) {
                onClose()
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [invitedTeamMembers]
    )

    const areInvitesCreatable = invites.length + 1 < MAX_INVITES_AT_ONCE
    const areInvitesDeletable = invites.length > 1
    const validInvitesCount = invites.filter((invite) => invite.isValid && invite.target_email).length

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
            okButtonProps={{ disabled: !canSubmit, loading: invitedTeamMembersLoading }}
            cancelButtonProps={{ disabled: invitedTeamMembersLoading }}
            closable={!invitedTeamMembersLoading}
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

                    {invites.map((_, index) => (
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
