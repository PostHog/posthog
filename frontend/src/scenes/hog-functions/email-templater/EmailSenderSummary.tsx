import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonLabel } from '@posthog/lemon-ui'

import { senderAddressError, senderFrom, senderIntegrationFor } from './emailSenderFields'
import { EmailSenderForm } from './EmailSenderForm'
import { emailTemplaterLogic } from './emailTemplaterLogic'

export function EmailSenderSummary(): JSX.Element {
    const { emailTemplate, senderIntegrations: senders } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue } = useActions(emailTemplaterLogic)
    const [isEditing, setIsEditing] = useState(false)

    const from = senderFrom(emailTemplate)
    const sender = senderIntegrationFor(emailTemplate, senders)
    const name = from.name || sender?.config?.name
    const address = from.email || sender?.config?.email
    const replyTo = emailTemplate.replyTo || sender?.config?.reply_to
    const addressError = senderAddressError(from.email, sender)

    return (
        <div className="flex gap-2 items-center pl-2 pr-1 py-1 border-b shrink-0 min-w-0">
            <LemonLabel className="shrink-0">From</LemonLabel>
            <div className="flex-1 min-w-0 px-2">
                {sender ? (
                    <div className="truncate">
                        {name ? <span className="font-semibold">{name}</span> : null}
                        <span className="text-secondary">{name ? ` <${address}>` : address}</span>
                    </div>
                ) : (
                    <div className="text-secondary">Choose who this email comes from</div>
                )}
                {replyTo ? <div className="text-xs text-secondary truncate">{`Replies go to ${replyTo}`}</div> : null}
                {addressError ? <div className="text-xs text-danger">{addressError}</div> : null}
            </div>
            <LemonDropdown
                visible={isEditing}
                onVisibilityChange={setIsEditing}
                closeOnClickInside={false}
                placement="bottom-end"
                overlay={
                    <EmailSenderForm
                        from={from}
                        replyTo={emailTemplate.replyTo}
                        senders={senders}
                        onChangeFrom={(next) => setEmailTemplateValue('from', next)}
                        onChangeReplyTo={(next) => setEmailTemplateValue('replyTo', next)}
                        onDone={() => setIsEditing(false)}
                    />
                }
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPencil />}
                    status={addressError ? 'danger' : 'default'}
                    data-attr="transactional-email-sender-edit"
                >
                    {sender ? 'Edit sender' : 'Choose sender'}
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
