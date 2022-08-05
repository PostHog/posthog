import { Alert, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import './InviteModal.scss'
import { isEmail, pluralize } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from './inviteLogic'
import { IconDelete, IconOpenInNew, IconPlus } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonModal } from 'lib/components/LemonModal'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonTextArea, LemonInput } from '@posthog/lemon-ui'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { OrganizationInviteType } from '~/types'
import { userLogic } from 'scenes/userLogic'

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

    return (
        <div className="flex gap-2">
            <div className="flex-1">
                <LemonInput
                    placeholder={`${name.toLowerCase()}@posthog.com`}
                    type="email"
                    className={`error-on-blur${!invitesToSend[index]?.isValid ? ' errored' : ''}`}
                    onChange={(v) => {
                        let isValid = true
                        if (v && !isEmail(v)) {
                            isValid = false
                        }
                        updateInviteAtIndex({ target_email: v, isValid }, index)
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
            </div>
            <div className="flex-1 flex justify-between">
                {!preflight?.email_service_available ? (
                    <LemonButton
                        type="secondary"
                        disabled={!isEmail(invitesToSend[index].target_email)}
                        onClick={() => {
                            inviteTeamMembers()
                        }}
                        data-attr="invite-generate-invite-link"
                    >
                        Submit
                    </LemonButton>
                ) : (
                    <LemonInput
                        placeholder={name}
                        className="flex-1"
                        onChange={(v) => {
                            updateInviteAtIndex({ first_name: v }, index)
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                inviteTeamMembers()
                            }
                        }}
                    />
                )}
                {isDeletable && (
                    <LemonButton icon={<IconDelete />} status="danger" onClick={() => deleteInviteAtIndex(index)} />
                )}
            </div>
        </div>
    )
}

export function InviteModal({ visible, onClose }: { visible: boolean; onClose: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, canSubmit, invitedTeamMembersInternalLoading: loading, invites } = useValues(inviteLogic)
    const { appendInviteRow, resetInviteRows, inviteTeamMembers, deleteInvite, updateMessage } = useActions(inviteLogic)

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
                destroyOnClose
                title={<div className="invite-modal-header">Invite team members</div>}
            >
                <h1 className="font-extrabold">Invite others to {user?.organization?.name || 'PostHog'}</h1>
                {preflight?.email_service_available ? (
                    <p>
                        Invite others to your project to collaborate together in PostHog. An invite is specific to an
                        email address and expires after 3 days. Name can be provided for the team member's convenience.{' '}
                    </p>
                ) : (
                    <p>
                        This PostHog instance isn't configured to send emails. In the meantime, you can generate a link
                        for each team member you want to invite. You can always invite others at a later time.{' '}
                        <strong>Make sure you share links with the project members you want to invite.</strong>
                    </p>
                )}
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
                <div className="bulk-invite-modal space-y-2">
                    <div className="flex gap-2">
                        <b className="flex-1">Email address</b>
                        <b className="flex-1">
                            {preflight?.email_service_available ? 'Name (optional)' : 'Invite link'}
                        </b>
                    </div>

                    {invites.map((invite: OrganizationInviteType) => {
                        return (
                            <div className="flex gap-2 items-start" key={invite.id}>
                                <div className="flex-1 border">
                                    <div className="rounded p-2">{invite.target_email} </div>
                                </div>
                                <div className="flex-1 flex gap-2">
                                    {invite.is_expired ? (
                                        <b>Expired! Delete and recreate</b>
                                    ) : (
                                        <>
                                            {preflight?.email_service_available ? (
                                                <div className="flex-1 border rounded p-2"> {invite.first_name} </div>
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
                                                            padding: '0.5rem',
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
                                </div>
                            </div>
                        )
                    })}

                    {invitesToSend.map((_, index) => (
                        <InviteRow index={index} key={index.toString()} isDeletable={areInvitesDeletable} />
                    ))}

                    <div className="my-4">
                        {areInvitesCreatable && (
                            <LemonButton
                                type="secondary"
                                size="large"
                                icon={<IconPlus />}
                                onClick={appendInviteRow}
                                fullWidth
                                center
                            >
                                Add email address
                            </LemonButton>
                        )}
                    </div>
                </div>
                {preflight?.email_service_available && (
                    <div className="mb-4">
                        <div className="mb-2">
                            <b>Message</b> (optional)
                        </div>
                        <LemonTextArea
                            data-attr="invite-optional-message"
                            placeholder="Tell your teammates why you're inviting them to PostHog"
                            onChange={(e) => updateMessage(e)}
                        />
                    </div>
                )}
                <LemonDivider thick dashed />
                <div className="mt-4">
                    {!preflight?.email_service_available ? (
                        <LemonButton size="large" fullWidth center type="primary" onClick={onClose}>
                            Done
                        </LemonButton>
                    ) : (
                        <>
                            <LemonButton
                                onClick={() => inviteTeamMembers()}
                                className="mb-2"
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
            </LemonModal>
        </div>
    )
}
