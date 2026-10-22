import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { urls } from 'scenes/urls'

import {
    EmailSender,
    addressFromLocalPart,
    addressLocalPart,
    senderAddressError,
    senderDomain,
} from './emailSenderFields'
import { EmailTemplateFrom } from './types'

const ADD_SENDER = -1

function senderLabel(sender: EmailSender): string {
    const { name, email } = sender.config ?? {}
    return name && email ? `${name} <${email}>` : (email ?? sender.display_name ?? `Sender ${sender.id}`)
}

export function EmailSenderForm({
    from,
    replyTo,
    senders,
    onChangeFrom,
    onChangeReplyTo,
    onDone,
}: {
    from: EmailTemplateFrom
    replyTo: string | undefined
    senders: EmailSender[]
    onChangeFrom: (from: EmailTemplateFrom) => void
    onChangeReplyTo: (replyTo: string) => void
    onDone: () => void
}): JSX.Element {
    const sender = senders.find((candidate) => candidate.id === from.integrationId)
    const domain = senderDomain(sender)
    const senderEmail = sender?.config?.email
    const localPart = addressLocalPart(from.email, domain)

    const onChangeSender = (integrationId: number): void => {
        if (integrationId === ADD_SENDER) {
            window.open(urls.workflows('channels'), '_blank')
            return
        }
        // A custom address keeps its part before the @ and moves to the new sender's domain.
        const nextDomain = senderDomain(senders.find((candidate) => candidate.id === integrationId))
        const email = from.email ? addressFromLocalPart(addressLocalPart(from.email, domain), nextDomain) : undefined
        onChangeFrom({ ...from, integrationId, email })
    }

    return (
        <div className="flex flex-col gap-3 p-2 w-100 max-w-full">
            <LemonField.Pure label="Sender">
                <LemonSelect
                    fullWidth
                    placeholder="Choose a sender"
                    value={from.integrationId}
                    onChange={onChangeSender}
                    options={[
                        {
                            options: senders.map((candidate) => ({
                                value: candidate.id,
                                label: senderLabel(candidate),
                            })),
                        },
                        { options: [{ value: ADD_SENDER, label: 'Add new email sender', icon: <IconExternal /> }] },
                    ]}
                    data-attr="transactional-email-sender-select"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Display name" help="Shown in the inbox. Supports Liquid templating.">
                <LemonInput
                    value={from.name ?? ''}
                    placeholder={sender?.config?.name || "The sender's name"}
                    onChange={(name) => onChangeFrom({ ...from, name: name || undefined })}
                    data-attr="transactional-email-sender-name"
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Address"
                help={senderEmail ? `Leave empty to send from ${senderEmail}.` : undefined}
                error={senderAddressError(from.email, sender)}
            >
                <LemonInput
                    value={localPart}
                    placeholder={senderEmail?.split('@')[0]}
                    // A pasted full address already has its own domain, so the suffix would only confuse it.
                    suffix={
                        domain && !localPart.includes('@') ? (
                            <span className="text-secondary">{`@${domain}`}</span>
                        ) : undefined
                    }
                    onChange={(localPart) => onChangeFrom({ ...from, email: addressFromLocalPart(localPart, domain) })}
                    data-attr="transactional-email-sender-address"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Reply-to" help="Separate several addresses with commas.">
                <LemonInput
                    value={replyTo ?? ''}
                    placeholder={sender?.config?.reply_to || 'Replies go to the sender address'}
                    onChange={onChangeReplyTo}
                    data-attr="transactional-email-reply-to"
                />
            </LemonField.Pure>
            <div className="flex justify-end">
                <LemonButton type="primary" size="small" onClick={onDone}>
                    Done
                </LemonButton>
            </div>
        </div>
    )
}
