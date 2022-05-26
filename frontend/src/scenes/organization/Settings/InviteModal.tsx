import { Alert, Col, Input, Row, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import './InviteModal.scss'
import { isEmail, pluralize } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from './inviteLogic'
import { IconClose, IconDelete, IconOpenInNew, IconPlus } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonModal } from 'lib/components/LemonModal'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonTextArea } from '~/packages/apps-common'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { OrganizationInviteType } from '~/types'

/** Shuffled placeholder names */
const PLACEHOLDER_NAMES: string[] = [...Array(10).fill('Jane'), ...Array(10).fill('John'), 'Sonic'].sort(
    () => Math.random() - 0.5
)
const MAX_INVITES_AT_ONCE = 20

export function EmailUnavailableMessage(): JSX.Element {
    return (
        <AlertMessage type="info" style={{ marginTop: 16 }}>
            <>
                This PostHog instance isn't{' '}
                <a href="https://posthog.com/docs/self-host/configure/email" target="_blank" rel="noopener">
                    configured&nbsp;to&nbsp;send&nbsp;emails&nbsp;
                    <IconOpenInNew />
                </a>
                .<br />
                Remember to <u>share the invite link</u> with each team member you invite.
            </>
        </AlertMessage>
    )
}

function InviteRow({ index, isDeletable }: { index: number; isDeletable: boolean }): JSX.Element {
    const name = PLACEHOLDER_NAMES[index % PLACEHOLDER_NAMES.length]

    const { invitesToSend } = useValues(inviteLogic)
    const { updateInviteAtIndex, inviteTeamMembers, deleteInviteAtIndex } = useActions(inviteLogic)
    const { preflight } = useValues(preflightLogic)
    const { onboardingSidebarEnabled } = useValues(ingestionLogic)

    return (
        <Row gutter={16} className="invite-row" align="middle">
            <Col xs={isDeletable || onboardingSidebarEnabled ? 11 : 12}>
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
                    style={{ padding: 16 }}
                    value={invitesToSend[index]?.target_email}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            inviteTeamMembers()
                        }
                    }}
                    autoFocus={index === 0}
                    data-attr="invite-email-input"
                />
            </Col>
            {!preflight?.email_service_available && (
                <Col xs={isDeletable || onboardingSidebarEnabled ? 11 : 12}>
                    {onboardingSidebarEnabled && !preflight?.email_service_available ? (
                        <LemonButton
                            type="secondary"
                            style={{ padding: '16px 24px' }}
                            disabled={!isEmail(invitesToSend[index].target_email)}
                            onClick={() => {
                                inviteTeamMembers()
                            }}
                        >
                            Submit
                        </LemonButton>
                    ) : (
                        <Input
                            placeholder={name}
                            onChange={(e) => {
                                updateInviteAtIndex({ first_name: e.target.value }, index)
                            }}
                            style={{ padding: 16 }}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    inviteTeamMembers()
                                }
                            }}
                        />
                    )}
                </Col>
            )}
            {isDeletable && (
                <LemonButton icon={<IconDelete />} status="danger" onClick={() => deleteInviteAtIndex(index)} />
            )}
        </Row>
    )
}

export function InviteModal({ visible, onClose }: { visible: boolean; onClose: () => void }): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, canSubmit, invitedTeamMembersInternalLoading: loading, invites } = useValues(inviteLogic)
    const { appendInviteRow, resetInviteRows, inviteTeamMembers, deleteInvite, hideInviteModal, updateMessage } =
        useActions(inviteLogic)
    const { onboardingSidebarEnabled } = useValues(ingestionLogic)

    const areInvitesCreatable = invitesToSend.length + 1 < MAX_INVITES_AT_ONCE
    const areInvitesDeletable = invitesToSend.length > 1
    const validInvitesCount = invitesToSend.filter((invite) => invite.isValid && invite.target_email).length

    return (
        <div className="InviteModal">
            <LemonModal
                visible={visible}
                width="auto"
                style={{ maxWidth: 600 }}
                bodyStyle={{ padding: '0px 40px 40px 40px' }}
                onCancel={() => {
                    resetInviteRows()
                    onClose()
                }}
                closable={false}
                title={
                    <div className="invite-modal-header">
                        Invite team members
                        <LemonButton
                            icon={<IconClose />}
                            type="stealth"
                            size="small"
                            disabled={loading}
                            onClick={() => {
                                resetInviteRows()
                                onClose()
                            }}
                        />
                    </div>
                }
            >
                <h1 className="fw-800">Invite others to PostHog</h1>
                {onboardingSidebarEnabled && !preflight?.email_service_available && (
                    <p>
                        This PostHog instance isn't configured to send emails. In the meantime, you can generate a link
                        for each team member you want to invite. You can always invite others at a later time.
                    </p>
                )}
                <p>
                    Invites <b>expire after 3 days</b>.
                </p>
                <LemonDivider dashed thick />
                {preflight?.licensed_users_available === 0 && (
                    <Alert
                        type="warning"
                        showIcon
                        message={
                            <>
                                You've hit the limit of team members you can invite to your PostHog instance given your
                                license. Please contact <a href="mailto:sales@posthog.com">sales@posthog.com</a> to
                                upgrade your license.
                            </>
                        }
                    />
                )}
                <div className="bulk-invite-modal">
                    <Row gutter={16}>
                        <Col xs={areInvitesDeletable || onboardingSidebarEnabled ? 11 : 12}>
                            <b>Email address</b>
                        </Col>
                        <Col xs={areInvitesDeletable || onboardingSidebarEnabled ? 11 : 12}>
                            <b>
                                {onboardingSidebarEnabled && !preflight?.email_service_available
                                    ? 'Share link'
                                    : 'Name (optional)'}
                            </b>
                        </Col>
                    </Row>

                    {onboardingSidebarEnabled &&
                        invites.map((invite: OrganizationInviteType) => {
                            return (
                                <Row gutter={16} align="middle" className="mb mt" key={invite.id}>
                                    <Col xs={11}>
                                        <Input
                                            disabled
                                            style={{ backgroundColor: 'white', color: 'black', padding: 16 }}
                                            defaultValue={invite.target_email}
                                        />
                                    </Col>
                                    <Col xs={11}>
                                        {invite.is_expired ? (
                                            <b>Expired! Delete and recreate</b>
                                        ) : (
                                            <>
                                                {preflight?.email_service_available ? (
                                                    <Input
                                                        disabled
                                                        style={{
                                                            backgroundColor: 'white',
                                                            color: 'black',
                                                            padding: 16,
                                                        }}
                                                        defaultValue={invite.first_name}
                                                    />
                                                ) : (
                                                    <div>
                                                        <CopyToClipboardInline
                                                            data-attr="invite-link"
                                                            explicitValue={
                                                                new URL(`/signup/${invite.id}`, document.baseURI).href
                                                            }
                                                            description="invite link"
                                                            style={{
                                                                color: 'var(--primary)',
                                                                background: 'var(--bg-side)',
                                                                borderRadius: 4,
                                                                padding: 16,
                                                            }}
                                                        >
                                                            <div className="InviteModal__share_link">
                                                                {new URL(`/signup/${invite.id}`, document.baseURI).href}
                                                            </div>
                                                        </CopyToClipboardInline>
                                                    </div>
                                                )}
                                            </>
                                        )}
                                    </Col>
                                    <LemonButton
                                        title="Cancel the invite"
                                        data-attr="invite-delete"
                                        icon={<IconDelete />}
                                        status="danger"
                                        onClick={() => {
                                            invite.is_expired
                                                ? deleteInvite(invite)
                                                : Modal.confirm({
                                                      title: `Do you want to cancel the invite for ${invite.target_email}?`,
                                                      okText: 'Yes, cancel invite',
                                                      okType: 'danger',
                                                      onOk() {
                                                          deleteInvite(invite)
                                                      },
                                                      cancelText: 'No, keep invite',
                                                  })
                                        }}
                                    />
                                </Row>
                            )
                        })}

                    {invitesToSend.map((_, index) => (
                        <InviteRow index={index} key={index.toString()} isDeletable={areInvitesDeletable} />
                    ))}

                    <div className="mt mb">
                        {areInvitesCreatable && (
                            <LemonButton
                                type="secondary"
                                style={{ padding: '1rem' }}
                                icon={<IconPlus style={{ color: 'var(--primary)' }} />}
                                onClick={appendInviteRow}
                                fullWidth
                                center
                            >
                                Add email address
                            </LemonButton>
                        )}
                    </div>
                </div>
                {onboardingSidebarEnabled && preflight?.email_service_available && (
                    <div className="mb">
                        <div className="mb-05">
                            <b>Message</b> (optional)
                        </div>
                        <LemonTextArea
                            placeholder="Tell your teammates why you're inviting them to PostHog"
                            onChange={(e) => updateMessage(e)}
                        />
                    </div>
                )}
                <LemonDivider thick dashed />
                <div className="mt">
                    {onboardingSidebarEnabled && !preflight?.email_service_available ? (
                        <LemonButton style={{ padding: '1rem' }} fullWidth center type="primary" onClick={onClose}>
                            Done
                        </LemonButton>
                    ) : (
                        <>
                            <LemonButton
                                onClick={() => {
                                    inviteTeamMembers()
                                    if (!loading) {
                                        hideInviteModal()
                                    }
                                }}
                                className="mb-05"
                                type="primary"
                                fullWidth
                                center
                                disabled={!canSubmit}
                                data-attr="invite-team-member-submit"
                            >
                                {validInvitesCount ? `Invite ${pluralize(validInvitesCount, 'user')}` : 'Invite users'}
                            </LemonButton>
                            <LemonButton
                                onClick={() => {
                                    resetInviteRows()
                                    onClose()
                                }}
                                type="secondary"
                                fullWidth
                                center
                            >
                                Cancel
                            </LemonButton>
                        </>
                    )}
                </div>

                {!preflight?.email_service_available && !onboardingSidebarEnabled && <EmailUnavailableMessage />}
            </LemonModal>
        </div>
    )
}
