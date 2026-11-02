import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonLabel } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { EmailSenderDetails } from './EmailSenderDetails'
import { senderAddressError, senderFrom, senderIntegrationFor } from './emailSenderFields'
import { EmailSenderForm } from './EmailSenderForm'
import { emailTemplaterLogic } from './emailTemplaterLogic'

export function EmailSenderSummary(): JSX.Element {
    const { emailTemplate } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue } = useActions(emailTemplaterLogic)
    const { integrations } = useValues(integrationsLogic)
    const [isEditing, setIsEditing] = useState(false)

    const senders = (integrations ?? []).filter((integration) => integration.kind === 'email')
    const from = senderFrom(emailTemplate)
    const sender = senderIntegrationFor(emailTemplate, senders)
    const addressError = senderAddressError(from.email, sender)

    return (
        <div className="flex gap-2 items-center pl-2 pr-1 py-1 border-b shrink-0 min-w-0">
            <LemonLabel className="shrink-0">From</LemonLabel>
            <EmailSenderDetails
                email={emailTemplate}
                senders={senders}
                placeholder="Choose who this email comes from"
                className="flex-1 px-2"
            />
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
