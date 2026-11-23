import { LemonButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import {
    EmailSender,
    SenderDataAttrPrefix,
    addressFromLocalPart,
    addressLocalPart,
    isSingleTemplateExpression,
    selectedSenders,
    senderAddressError,
    sharedSenderDomain,
} from './emailSenderFields'
import { LiquidSupportedText } from './LiquidSupportedText'
import { EmailTemplateFrom } from './types'

/** The optional overrides on top of the chosen senders: display name, address, and reply-to. */
export function EmailSenderForm({
    from,
    replyTo,
    senders,
    variables,
    dataAttrPrefix,
    onChangeFrom,
    onChangeReplyTo,
    onClear,
    onDone,
}: {
    from: EmailTemplateFrom
    replyTo: string | undefined
    senders: EmailSender[]
    /** Sample values for templating. When set, the name and reply-to take Liquid with a variable picker. */
    variables?: Record<string, any>
    dataAttrPrefix: SenderDataAttrPrefix
    onChangeFrom: (from: EmailTemplateFrom) => void
    onChangeReplyTo: (replyTo: string) => void
    onClear: () => void
    /** Shows a Done button, for when the form sits in a dropdown. */
    onDone?: () => void
}): JSX.Element {
    const selected = selectedSenders(from, senders)
    const domain = sharedSenderDomain(selected)
    const localPart = addressLocalPart(from.email, domain)
    const wholeAddressTemplate = !!domain && isSingleTemplateExpression(localPart)
    const single = selected.length === 1 ? selected[0] : undefined
    // Senders on different domains can only send from their own addresses.
    const mixedDomains = selected.length > 1 && !domain
    const hasOverrides = !!(from.name || from.email || replyTo)

    const textInput = (
        value: string | undefined,
        onChange: (value: string) => void,
        placeholder: string,
        dataAttr: string
    ): JSX.Element =>
        variables ? (
            <div className="border rounded bg-surface-primary px-1" data-attr={dataAttr}>
                <LiquidSupportedText
                    value={value ?? ''}
                    onChange={(next) => onChange(next ?? '')}
                    globals={variables}
                />
            </div>
        ) : (
            <LemonInput value={value ?? ''} placeholder={placeholder} onChange={onChange} data-attr={dataAttr} />
        )

    return (
        <div className="flex flex-col gap-3 p-2 w-100 max-w-full">
            <LemonField.Pure
                label="Display name"
                help={
                    single?.config?.name
                        ? `Shown in the inbox. Leave empty to use ${single.config.name}.`
                        : "Shown in the inbox. Leave empty to use the sender's name."
                }
            >
                {textInput(
                    from.name,
                    (name) => onChangeFrom({ ...from, name: name || undefined }),
                    single?.config?.name || "The sender's name",
                    `${dataAttrPrefix}-sender-name`
                )}
            </LemonField.Pure>
            <LemonField.Pure
                label="Address"
                help={
                    mixedDomains
                        ? 'Your senders are on different domains, so each one sends from its own address.'
                        : wholeAddressTemplate
                          ? `This value is used as the full address. To use it as the part before the @, add @${domain} after it.`
                          : single?.config?.email
                            ? `Leave empty to send from ${single.config.email}.`
                            : "Leave empty to send from each sender's own address."
                }
                error={senderAddressError(from.email, selected)}
            >
                <LemonInput
                    value={localPart}
                    // An address already set stays editable so it can be cleared.
                    disabled={mixedDomains && !from.email}
                    placeholder={single?.config?.email?.split('@')[0] ?? 'Sender address'}
                    // A pasted full address already has its own domain, so the suffix would only confuse it.
                    suffix={
                        domain && !localPart.includes('@') && !wholeAddressTemplate ? (
                            <span className="text-secondary">{`@${domain}`}</span>
                        ) : undefined
                    }
                    onChange={(next) => onChangeFrom({ ...from, email: addressFromLocalPart(next, domain) })}
                    data-attr={`${dataAttrPrefix}-sender-address`}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Reply-to" help="Separate several addresses with commas.">
                {textInput(
                    replyTo,
                    onChangeReplyTo,
                    single?.config?.reply_to || 'Replies go to the sender address',
                    `${dataAttrPrefix}-reply-to`
                )}
            </LemonField.Pure>
            {hasOverrides || onDone ? (
                <div className="flex gap-2 justify-end">
                    {hasOverrides ? (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            onClick={onClear}
                            data-attr={`${dataAttrPrefix}-custom-sender-clear`}
                        >
                            Clear
                        </LemonButton>
                    ) : null}
                    {onDone ? (
                        <LemonButton type="primary" size="small" onClick={onDone}>
                            Done
                        </LemonButton>
                    ) : null}
                </div>
            ) : null}
        </div>
    )
}
