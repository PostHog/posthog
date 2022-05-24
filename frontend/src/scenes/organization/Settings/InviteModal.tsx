import { Alert, Col, Input, Row, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
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

    const { invitesToSend, invites } = useValues(inviteLogic)
    const { updateInviteAtIndex, inviteTeamMembers, deleteInviteAtIndex } = useActions(inviteLogic)
    const { preflight } = useValues(preflightLogic)
    const { onboardingSidebar } = useValues(ingestionLogic)

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
                    data-attr="invite-email-input"
                />
            </Col>
            {!preflight?.email_service_unavailable && <Col xs={isDeletable ? 11 : 12}>

                {true ? (
                    <LemonButton type="secondary" onClick={() => { inviteTeamMembers() }}>Submit</LemonButton>
                ) :
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
                    />}

            </Col>}
            {isDeletable && (
                <Col xs={2}>
                    <LemonButton
                        icon={<IconDelete />}
                        type="alt"
                        onClick={() => deleteInviteAtIndex(index)}
                        size="small"
                    />
                </Col>
            )}
        </Row>
    )
}

export function InviteModal({ visible, onClose }: { visible: boolean; onClose: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, canSubmit, invitedTeamMembersInternalLoading: loading, invites } = useValues(inviteLogic)
    const { appendInviteRow, resetInviteRows, inviteTeamMembers, deleteInvite } = useActions(inviteLogic)
    // const { onboardingSidebar } = useValues(ingestionLogic)
    const onboardingSidebar = true

    const areInvitesCreatable = invitesToSend.length + 1 < MAX_INVITES_AT_ONCE
    const areInvitesDeletable = invitesToSend.length > 1
    const validInvitesCount = invitesToSend.filter((invite) => invite.isValid && invite.target_email).length

    return (
        <LemonModal
            visible={visible}
            width="auto"
            style={{ maxWidth: 600 }}
            bodyStyle={{ padding: 40 }}
            onCancel={() => {
                resetInviteRows()
                onClose()
            }}
        >
            <p className="text-muted">Invite team members</p>
            <h1 className="fw-800">Invite others to PostHog</h1>
            {onboardingSidebar && !preflight?.email_service_unavailable && <p>This PostHog instance isn't configured to send emails. In the meantime, you can generate a link for each team member you want to invite. You can always invite others at a later time.</p>}
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
                            license. Please contact <a href="mailto:sales@posthog.com">sales@posthog.com</a> to upgrade
                            your license.
                        </>
                    }
                />
            )}
            <div className="bulk-invite-modal">
                <Row gutter={16}>
                    <Col xs={areInvitesDeletable ? 11 : 12}>
                        <b>Email address</b>
                    </Col>
                    <Col xs={areInvitesDeletable ? 11 : 12}>
                        <b>
                            {preflight?.email_service_available ? 'Name (optional)' : 'Share link'}
                        </b>
                    </Col>
                </Row>

                {invites.map((invite: OrganizationInviteType) => {
                    return (
                        <Row gutter={16} align="middle" className="mb">
                            <Col xs={11}><div style={{ border: '1px solid var(--border)', borderRadius: 4, padding: '4px 11px' }}>{invite.target_email}</div></Col>
                            <Col xs={11}>
                                {invite.is_expired ? (
                                    <b>Expired! Delete and recreate</b>
                                ) : (
                                    <CopyToClipboardInline data-attr="invite-link" description="invite link" style={{ color: 'var(--primary)', background: 'var(--bg-side)', borderRadius: 4, padding: '4px 11px' }}>
                                        {new URL(`/signup/${invite.id}`, document.baseURI).href}
                                    </CopyToClipboardInline>
                                )}
                            </Col>
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
                        <LemonButton type="secondary" icon={<IconPlus style={{ color: 'var(--primary)' }} />} onClick={appendInviteRow} fullWidth center>
                            Add email address
                        </LemonButton>
                    )}
                </div>

            </div>
            {onboardingSidebar && preflight?.email_service_available && <div className="mb">
                <div><b>Message</b> (optional)</div>
                <LemonTextArea />
            </div>}
            <LemonDivider thick dashed />
            <div className="mt">
                {preflight?.email_service_available ?
                    <>
                        <LemonButton onClick={inviteTeamMembers} className="mb-05" type="primary" fullWidth center disabled={!validInvitesCount}>{validInvitesCount ? `Invite ${pluralize(validInvitesCount, 'user')}` : 'Invite users'}</LemonButton>
                        <LemonButton
                            onClick={() => {
                                resetInviteRows()
                                onClose()
                            }} type="secondary" fullWidth center>Cancel</LemonButton>
                    </> : <LemonButton fullWidth center type="primary" onClick={onClose}>Done</LemonButton>
                }
            </div>

            {/* {!preflight?.email_service_available && <EmailUnavailableMessage />} */}

        </LemonModal>
        // <Modal
        //     title={`Inviting team members${user?.organization ? ' to ' + user?.organization?.name : ''}`}
        //     visible={visible}
        //     onCancel={() => {
        //         resetInviteRows()
        //         onClose()
        //     }}
        //     onOk={inviteTeamMembers}
        //     okText={validInvitesCount ? `Invite ${pluralize(validInvitesCount, 'team member')}` : 'Invite team members'}
        //     destroyOnClose
        //     okButtonProps={{
        //         disabled: !canSubmit,
        //         loading,
        //         // @ts-expect-error - data-attr works just fine despite not being in ButtonProps
        //         'data-attr': 'invite-team-member-submit',
        //     }}
        //     cancelButtonProps={{ disabled: loading }}
        //     closable={!loading}
        // >
        // {preflight?.licensed_users_available === 0 ? (
        //     <Alert
        //         type="warning"
        //         showIcon
        //         message={
        //             <>
        //                 You've hit the limit of team members you can invite to your PostHog instance given your
        //                 license. Please contact <a href="mailto:sales@posthog.com">sales@posthog.com</a> to upgrade
        //                 your license.
        //             </>
        //         }
        //     />
        // ) : (
        // </Modal>
    )
}
