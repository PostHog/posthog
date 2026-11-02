import { cn } from 'lib/utils/css-classes'

import { EmailSender, senderAddressError, senderFrom, senderIntegrationFor } from './emailSenderFields'
import { EmailTemplate } from './types'

export function EmailSenderDetails({
    email,
    senders,
    placeholder,
    className,
}: {
    email: Partial<EmailTemplate>
    senders: EmailSender[]
    placeholder: string
    className?: string
}): JSX.Element {
    const from = senderFrom(email)
    const sender = senderIntegrationFor(email, senders)
    const name = from.name || sender?.config?.name
    const address = from.email || sender?.config?.email
    const replyTo = email.replyTo || sender?.config?.reply_to
    const addressError = senderAddressError(from.email, sender)

    return (
        <div className={cn('min-w-0', className)}>
            {sender ? (
                <div className="truncate">
                    {name ? <span className="font-semibold">{name}</span> : null}
                    <span className="text-secondary">{name ? ` <${address}>` : address}</span>
                </div>
            ) : (
                <div className="text-secondary">{placeholder}</div>
            )}
            {replyTo ? <div className="text-xs text-secondary truncate">{`Replies go to ${replyTo}`}</div> : null}
            {addressError ? <div className="text-xs text-danger">{addressError}</div> : null}
        </div>
    )
}
