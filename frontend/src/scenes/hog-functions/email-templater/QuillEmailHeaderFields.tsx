import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { ReactNode, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import {
    Button,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
    InputGroupText,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { isHeaderFieldShown } from './emailHeaderFields'
import {
    EmailSender,
    addressFromLocalPart,
    addressLocalPart,
    fromRowError,
    fromWithSenders,
    isSingleTemplateExpression,
    selectedSenderIds,
    selectedSenders,
    senderAddressError,
    senderFrom,
    sharedSenderDomain,
} from './emailSenderFields'
import { EMAIL_TYPE_SUPPORTED_FIELDS, emailTemplaterLogic } from './emailTemplaterLogic'
import { LiquidSupportedText } from './LiquidSupportedText'
import { EmailTemplate, MAX_WORKFLOW_EMAIL_SENDERS } from './types'

function senderLabel(sender: EmailSender): string {
    const { name, email } = sender.config ?? {}
    return name && email ? `${name} <${email}>` : (email ?? sender.display_name ?? `Sender ${sender.id}`)
}

/** Liquid parser errors read as "Liquid template error: <what>, line:1, col:29". One-line fields have no lines. */
export function readableFieldError(error: string | null | undefined): string | null | undefined {
    const match = error?.match(/^Liquid template error: (.*?)(?:, line:\d+, col:(\d+))?$/)
    if (!match) {
        return error
    }
    const [, problem, column] = match
    return `Liquid syntax problem${column ? ` at character ${column}` : ''}: ${problem}`
}

function HeaderField({
    label,
    error,
    description,
    stacked,
    aside,
    children,
}: {
    label: string
    error?: string | null
    description?: ReactNode
    stacked?: boolean
    aside?: ReactNode
    children: ReactNode
}): JSX.Element {
    const note = error ? (
        <FieldError>{readableFieldError(error)}</FieldError>
    ) : description ? (
        <FieldDescription>{description}</FieldDescription>
    ) : null
    if (stacked) {
        return (
            <Field data-invalid={error ? true : undefined} className="min-w-0">
                <FieldLabel>{label}</FieldLabel>
                {children}
                {note}
            </Field>
        )
    }
    return (
        <Field
            data-invalid={error ? true : undefined}
            className="grid min-w-0 grid-cols-[6rem_minmax(0,1fr)] items-start gap-x-3 gap-y-0.5"
        >
            <FieldLabel className="flex h-7 items-center">{label}</FieldLabel>
            <div className="flex min-w-0 items-center gap-3">
                <div className="min-w-0 flex-1">{children}</div>
                {aside}
            </div>
            {note ? <div className="col-start-2">{note}</div> : null}
        </Field>
    )
}

const LinkAction = React.forwardRef<HTMLButtonElement, React.ComponentProps<typeof Button>>(function LinkAction(
    { children, ...props },
    ref
) {
    return (
        <Button ref={ref} variant="link-muted" size="inline" className="text-xs" {...props}>
            {children}
        </Button>
    )
})

/** A Liquid-aware text field that looks like the other inputs: same border, height and font. */
function LiquidInput({
    value,
    onChange,
    placeholder,
    invalid,
    trailing,
}: {
    value: string
    onChange: (value?: string) => void
    placeholder?: string
    invalid?: boolean
    trailing?: ReactNode
}): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)
    return (
        <InputGroup size="sm" className="min-w-0 overflow-hidden">
            <div data-slot="input-group-control" aria-invalid={invalid || undefined} className="flex-1 min-w-0 pl-2">
                <LiquidSupportedText
                    value={value}
                    onChange={onChange}
                    globals={logicProps.variables}
                    placeholder={placeholder}
                    plain
                />
            </div>
            {trailing ? <InputGroupAddon align="inline-end">{trailing}</InputGroupAddon> : null}
        </InputGroup>
    )
}

type OptionalFieldKey = 'replyTo' | 'cc' | 'bcc' | 'preheader'

const OPTIONAL_FIELDS: Record<OptionalFieldKey, { label: string; placeholder: string }> = {
    replyTo: { label: 'Reply-to', placeholder: 'Where replies go, e.g. support@example.com' },
    cc: { label: 'Cc', placeholder: 'Addresses, separated by commas' },
    bcc: { label: 'Bcc', placeholder: 'Addresses, separated by commas' },
    preheader: {
        label: 'Preview text',
        placeholder: 'Shown next to the subject in most inboxes',
    },
}

function useOptionalFields(): {
    supports: (key: OptionalFieldKey) => boolean
    isShown: (key: OptionalFieldKey) => boolean
    reveal: (key: OptionalFieldKey) => void
} {
    const { logicProps, visibleFields } = useValues(emailTemplaterLogic)
    const { revealAdvancedField } = useActions(emailTemplaterLogic)
    const supported = EMAIL_TYPE_SUPPORTED_FIELDS[logicProps.type]
    return {
        supports: (key) => supported.some((field) => field.key === key),
        isShown: (key) => isHeaderFieldShown(visibleFields, key),
        reveal: (key) => {
            revealAdvancedField(key)
            posthog.capture('email header field added', { field: key, editor_type: logicProps.type })
        },
    }
}

function AddFieldButtons({ fields }: { fields: OptionalFieldKey[] }): JSX.Element | null {
    const { supports, isShown, reveal } = useOptionalFields()
    const hidden = fields.filter((field) => supports(field) && !isShown(field))
    if (!hidden.length) {
        return null
    }
    return (
        <>
            {hidden.map((field) => (
                // pinned: data-attr values feed autocapture dashboards
                <InputGroupButton
                    key={field}
                    size="xs"
                    onClick={() => reveal(field)}
                    aria-label={`Add ${OPTIONAL_FIELDS[field].label}`}
                    data-attr={`email-header-add-${field}`}
                >
                    <IconPlus />
                    {OPTIONAL_FIELDS[field].label}
                </InputGroupButton>
            ))}
        </>
    )
}

/** Display name and address on top of the chosen sender. */
function CustomSenderForm({ senders, onDone }: { senders: EmailSender[]; onDone: () => void }): JSX.Element {
    const { emailTemplate } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue } = useActions(emailTemplaterLogic)
    const from = senderFrom(emailTemplate)
    const selected = selectedSenders(from, senders)
    const domain = sharedSenderDomain(selected)
    const localPart = addressLocalPart(from.email, domain)
    const wholeAddressTemplate = !!domain && isSingleTemplateExpression(localPart)
    const single = selected.length === 1 ? selected[0] : undefined
    const mixedDomains = selected.length > 1 && !domain
    const addressError = senderAddressError(from.email, selected)
    const setFrom = (next: Partial<typeof from>): void => setEmailTemplateValue('from', { ...from, ...next })

    return (
        <div className="flex flex-col gap-3">
            <HeaderField
                label="Display name"
                stacked
                description={
                    single?.config?.name
                        ? `Leave empty to use ${single.config.name}.`
                        : "Leave empty to use the sender's name."
                }
            >
                <LiquidInput
                    value={from.name ?? ''}
                    onChange={(name) => setFrom({ name: name || undefined })}
                    placeholder={single?.config?.name || "The sender's name"}
                />
            </HeaderField>
            <HeaderField
                label="Address"
                stacked
                error={addressError}
                description={
                    mixedDomains
                        ? 'Your senders are on different domains, so each one sends from its own address.'
                        : wholeAddressTemplate
                          ? `This value is used as the full address. To use it as the part before the @, add @${domain} after it.`
                          : single?.config?.email
                            ? `Leave empty to send from ${single.config.email}.`
                            : "Leave empty to send from each sender's own address."
                }
            >
                <InputGroup size="sm">
                    <InputGroupInput
                        value={localPart}
                        className="pl-2"
                        disabled={mixedDomains && !from.email}
                        aria-invalid={addressError ? true : undefined}
                        placeholder={single?.config?.email?.split('@')[0] ?? 'Sender address'}
                        onChange={(event) => setFrom({ email: addressFromLocalPart(event.target.value, domain) })}
                        data-attr="workflow-email-sender-address"
                    />
                    {domain && !localPart.includes('@') && !wholeAddressTemplate ? (
                        <InputGroupAddon align="inline-end">
                            <InputGroupText>@{domain}</InputGroupText>
                        </InputGroupAddon>
                    ) : null}
                </InputGroup>
            </HeaderField>
            <div className="flex justify-end gap-2">
                {from.name || from.email ? (
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setFrom({ name: undefined, email: undefined })}
                        data-attr="workflow-email-custom-sender-clear"
                    >
                        Use sender's own
                    </Button>
                ) : null}
                <Button variant="primary" size="sm" onClick={onDone}>
                    Done
                </Button>
            </div>
        </div>
    )
}

function SenderField(): JSX.Element {
    const { emailTemplate, logicProps } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue } = useActions(emailTemplaterLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const rotationEnabled = useFeatureFlag('WORKFLOWS_EMAIL_SENDER_ROTATION')
    const [customOpen, setCustomOpen] = useState(false)

    const senders = (integrations ?? []).filter((integration) => integration.kind === 'email') as EmailSender[]
    const from = senderFrom(emailTemplate)
    const selected = selectedSenders(from, senders)
    const error = fromRowError(logicProps.fieldErrors?.from || senderAddressError(from.email, selected), selected)
    const rotation = logicProps.type === 'native_email' && rotationEnabled
    const custom = from.name && from.email ? `${from.name} <${from.email}>` : from.name || from.email || ''

    if (!integrationsLoading && senders.length === 0) {
        // The broadcast step shows a banner that sets up a sender, so this only says why the field is empty.
        return (
            <HeaderField label="From">
                <Select disabled items={[]} value={null}>
                    <SelectTrigger className="w-full min-w-0" data-attr="workflow-email-sender-select">
                        <SelectValue placeholder="No sender set up yet" />
                    </SelectTrigger>
                </Select>
            </HeaderField>
        )
    }

    const selectedIds = selectedSenderIds(from).map(String)
    const changeSenders = (ids: string[]): void => {
        const next = ids.map(Number).slice(0, MAX_WORKFLOW_EMAIL_SENDERS)
        setEmailTemplateValue('from', fromWithSenders(from, next, senders))
    }
    const placeholder = rotation ? 'Choose senders' : 'Choose a sender'

    const customize =
        selected.length || custom ? (
            <Popover open={customOpen} onOpenChange={setCustomOpen}>
                <PopoverTrigger render={<LinkAction />} data-attr="email-from-custom-sender">
                    {custom ? 'Edit name and address' : 'Change name or address'}
                </PopoverTrigger>
                <PopoverContent align="end" className="w-96 p-3">
                    <CustomSenderForm senders={senders} onDone={() => setCustomOpen(false)} />
                </PopoverContent>
            </Popover>
        ) : null

    return (
        <HeaderField
            label="From"
            error={error}
            description={custom ? <span className="block truncate">Sends as {custom}</span> : undefined}
            aside={customize}
        >
            <Select
                multiple={rotation}
                items={senders.map((sender) => ({ value: String(sender.id), label: senderLabel(sender) }))}
                value={rotation ? selectedIds : (selectedIds[0] ?? null)}
                onValueChange={(value: string | string[] | null) =>
                    changeSenders(Array.isArray(value) ? value : value ? [value] : [])
                }
            >
                <SelectTrigger
                    className="w-full min-w-0"
                    aria-invalid={error ? true : undefined}
                    data-attr="workflow-email-sender-select"
                >
                    <SelectValue placeholder={placeholder}>
                        {(value: string | string[] | null) => {
                            const ids = Array.isArray(value) ? value : value ? [value] : []
                            const labels = senders.filter((sender) => ids.includes(String(sender.id))).map(senderLabel)
                            return labels.length ? (
                                <span className="truncate">{labels.join(', ')}</span>
                            ) : (
                                <span className="text-muted-foreground">{placeholder}</span>
                            )
                        }}
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {senders.map((sender) => (
                        <SelectItem key={sender.id} value={String(sender.id)}>
                            {senderLabel(sender)}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </HeaderField>
    )
}

function OptionalField({ field }: { field: OptionalFieldKey }): JSX.Element {
    const { emailTemplate, logicProps } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue, hideAdvancedField } = useActions(emailTemplaterLogic)
    const { label, placeholder } = OPTIONAL_FIELDS[field]
    const error = field === 'preheader' ? logicProps.fieldErrors?.preheader : undefined
    return (
        <HeaderField label={label} error={error}>
            <LiquidInput
                value={((emailTemplate as EmailTemplate)[field] as string | undefined) ?? ''}
                onChange={(value) => setEmailTemplateValue(field, value ?? '')}
                placeholder={placeholder}
                invalid={!!error}
                trailing={
                    <InputGroupButton
                        size="icon-xs"
                        aria-label={`Remove ${label}`}
                        tooltip={`Remove ${label}`}
                        onClick={() => {
                            setEmailTemplateValue(field, '')
                            hideAdvancedField(field)
                        }}
                        data-attr={`email-header-remove-${field}`}
                    >
                        <IconX />
                    </InputGroupButton>
                }
            />
        </HeaderField>
    )
}

/** Optional fields are added from buttons inside the field they belong to, and appear right below it. */
export function QuillEmailHeaderFields(): JSX.Element {
    const { emailTemplate, logicProps } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue } = useActions(emailTemplaterLogic)
    const { supports, isShown } = useOptionalFields()
    const errors = logicProps.fieldErrors
    const shown = (key: OptionalFieldKey): boolean => supports(key) && isShown(key)
    // A workflow email's `to` is { email, name }, and only the address is edited here.
    const to = emailTemplate.to as unknown as { email?: string; name?: string } | undefined

    return (
        <div data-quill className="flex flex-col gap-2 border-b px-4 py-3" data-attr="email-header-fields">
            <SenderField />
            <HeaderField label="To" error={errors?.to}>
                <LiquidInput
                    value={to?.email ?? ''}
                    onChange={(email) => setEmailTemplateValue('to', { ...to, email: email ?? '' })}
                    placeholder="Who receives this email"
                    invalid={!!errors?.to}
                    trailing={<AddFieldButtons fields={['cc', 'bcc', 'replyTo']} />}
                />
            </HeaderField>
            {shown('cc') ? <OptionalField field="cc" /> : null}
            {shown('bcc') ? <OptionalField field="bcc" /> : null}
            {shown('replyTo') ? <OptionalField field="replyTo" /> : null}
            <HeaderField label="Subject" error={errors?.subject}>
                <LiquidInput
                    value={emailTemplate.subject ?? ''}
                    onChange={(subject) => setEmailTemplateValue('subject', subject ?? '')}
                    placeholder="What's this email about?"
                    invalid={!!errors?.subject}
                    trailing={<AddFieldButtons fields={['preheader']} />}
                />
            </HeaderField>
            {shown('preheader') ? <OptionalField field="preheader" /> : null}
        </div>
    )
}
