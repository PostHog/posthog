import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import { IconExternal, IconPencil, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { EmailHeaderRow } from './EmailHeaderRow'
import { selectedSenders, senderAddressError, senderFrom } from './emailSenderFields'
import { EmailSenderForm } from './EmailSenderForm'
import { EmailSenderPicker } from './EmailSenderPicker'
import { emailTemplaterLogic } from './emailTemplaterLogic'

/** The From row: pick senders in one click, and set a custom name, address, or reply-to only when needed. */
export function EmailSenderRow(): JSX.Element {
    const { emailTemplate, logicProps } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue, clearCustomSender } = useActions(emailTemplaterLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const senderRotationEnabled = useFeatureFlag('WORKFLOWS_EMAIL_SENDER_ROTATION')
    const [isEditing, setIsEditing] = useState(false)
    const openedWith = useRef<unknown>(null)

    // A workflow or broadcast email can rotate senders and fill sender fields from person data.
    // A transactional template sends from one sender with values from the API call.
    const isWorkflowEmail = logicProps.type === 'native_email'
    const dataAttrPrefix = isWorkflowEmail ? 'workflow-email' : 'transactional-email'
    const senders = (integrations ?? []).filter((integration) => integration.kind === 'email')
    const from = senderFrom(emailTemplate)
    const replyTo = emailTemplate.replyTo
    const selected = selectedSenders(from, senders)
    const addressError = senderAddressError(from.email, selected)
    const hasOverrides = !!(from.name || from.email || replyTo)

    const notes = [
        selected.length > 1 ? `Each run sends from one of ${selected.length} senders` : null,
        from.name || from.email
            ? `Sends as ${[from.name, from.email && `<${from.email}>`].filter(Boolean).join(' ')}`
            : null,
        replyTo ? `Replies go to ${replyTo}` : null,
    ].filter(Boolean)

    const onVisibilityChange = (visible: boolean): void => {
        if (visible) {
            openedWith.current = { from, replyTo }
        } else if (!objectsEqual(openedWith.current, { from, replyTo })) {
            posthog.capture('email sender edited', {
                editor_type: logicProps.type,
                sender_count: selected.length,
                has_custom_name: !!from.name,
                has_custom_address: !!from.email,
                has_reply_to: !!replyTo,
            })
        }
        setIsEditing(visible)
    }

    if (!integrationsLoading && senders.length === 0) {
        return (
            <EmailHeaderRow label="From" className="py-1">
                <div className="flex-1 min-w-0 text-secondary">No email senders yet</div>
                <LemonButton
                    size="small"
                    type="secondary"
                    to={urls.workflows('channels')}
                    targetBlank
                    icon={<IconExternal />}
                    data-attr={`${dataAttrPrefix}-sender-connect`}
                >
                    Connect email sender
                </LemonButton>
            </EmailHeaderRow>
        )
    }

    return (
        <EmailHeaderRow label="From" error={logicProps.fieldErrors?.from || addressError} className="py-1">
            <div className="flex-1 min-w-0">
                <EmailSenderPicker
                    from={from}
                    senders={senders}
                    allowRotation={isWorkflowEmail && senderRotationEnabled}
                    dataAttrPrefix={dataAttrPrefix}
                    onChangeFrom={(next) => setEmailTemplateValue('from', next)}
                />
                {notes.length > 0 ? (
                    <div className="flex flex-wrap gap-x-3 mt-0.5 text-xs text-secondary">
                        {notes.map((note) => (
                            <span key={note} className="min-w-0 truncate">
                                {note}
                            </span>
                        ))}
                    </div>
                ) : null}
            </div>
            <LemonDropdown
                visible={isEditing}
                onVisibilityChange={onVisibilityChange}
                closeOnClickInside={false}
                placement="bottom-end"
                overlay={
                    <EmailSenderForm
                        from={from}
                        replyTo={replyTo}
                        senders={senders}
                        variables={isWorkflowEmail ? logicProps.variables : undefined}
                        dataAttrPrefix={dataAttrPrefix}
                        onChangeFrom={(next) => setEmailTemplateValue('from', next)}
                        onChangeReplyTo={(next) => setEmailTemplateValue('replyTo', next)}
                        onClear={clearCustomSender}
                        onDone={() => onVisibilityChange(false)}
                    />
                }
            >
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    className="shrink-0"
                    icon={hasOverrides ? <IconPencil /> : <IconPlus />}
                    status={addressError ? 'danger' : 'default'}
                    tooltip="Set a display name, address, or reply-to for this email"
                    // pinned: data-attr values feed autocapture dashboards
                    data-attr={isWorkflowEmail ? 'email-from-custom-sender' : 'transactional-email-sender-edit'}
                >
                    Custom sender
                </LemonButton>
            </LemonDropdown>
        </EmailHeaderRow>
    )
}
