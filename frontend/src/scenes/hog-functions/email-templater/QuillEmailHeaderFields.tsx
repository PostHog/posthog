import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Field,
    FieldError,
    FieldLabel,
    InputGroup,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    cn,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { COPY_HEADER_FIELDS, OptionalHeaderField, PREHEADER_FIELD, isHeaderFieldShown } from './emailHeaderFields'
import {
    EmailSender,
    fromRowError,
    fromWithSenders,
    selectedSenderIds,
    selectedSenders,
    senderAddressError,
    senderFrom,
} from './emailSenderFields'
import { EmailSenderForm } from './EmailSenderForm'
import { EMAIL_TYPE_SUPPORTED_FIELDS, emailTemplaterLogic } from './emailTemplaterLogic'
import { LiquidSupportedText } from './LiquidSupportedText'
import { MAX_WORKFLOW_EMAIL_SENDERS } from './types'

function senderLabel(sender: EmailSender): string {
    const { name, email } = sender.config ?? {}
    return name && email ? `${name} <${email}>` : (email ?? sender.display_name ?? `Sender ${sender.id}`)
}

function HeaderField({
    label,
    error,
    className,
    children,
}: {
    label: string
    error?: string | null
    className?: string
    children: ReactNode
}): JSX.Element {
    return (
        <Field data-invalid={error ? true : undefined} className={cn('min-w-0', className)}>
            <FieldLabel>{label}</FieldLabel>
            {children}
            {error ? <FieldError>{error}</FieldError> : null}
        </Field>
    )
}

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
            {trailing}
        </InputGroup>
    )
}

function SenderField(): JSX.Element {
    const { emailTemplate, logicProps } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue, clearCustomSender } = useActions(emailTemplaterLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const rotationEnabled = useFeatureFlag('WORKFLOWS_EMAIL_SENDER_ROTATION')
    const [customOpen, setCustomOpen] = useState(false)

    const senders = (integrations ?? []).filter((integration) => integration.kind === 'email') as EmailSender[]
    const from = senderFrom(emailTemplate)
    const replyTo = emailTemplate.replyTo
    const selected = selectedSenders(from, senders)
    const error = fromRowError(logicProps.fieldErrors?.from || senderAddressError(from.email, selected), selected)
    const rotation = logicProps.type === 'native_email' && rotationEnabled
    const custom = [from.name, from.email && `<${from.email}>`].filter(Boolean).join(' ')

    if (!integrationsLoading && senders.length === 0) {
        return (
            <HeaderField label="From">
                <Button
                    variant="outline"
                    render={<LinkPrimitive to={urls.workflows('channels')} target="_blank" />}
                    data-attr="workflow-email-sender-connect"
                >
                    Connect an email sender
                </Button>
            </HeaderField>
        )
    }

    const selectedIds = selectedSenderIds(from).map(String)
    const changeSenders = (ids: string[]): void => {
        const next = ids.map(Number).slice(0, MAX_WORKFLOW_EMAIL_SENDERS)
        setEmailTemplateValue('from', fromWithSenders(from, next, senders))
    }

    return (
        <HeaderField label="From" error={error}>
            <div className="flex min-w-0 gap-1">
                <Select
                    multiple={rotation}
                    items={senders.map((sender) => ({ value: String(sender.id), label: senderLabel(sender) }))}
                    value={rotation ? selectedIds : (selectedIds[0] ?? null)}
                    onValueChange={(value: string | string[] | null) =>
                        changeSenders(Array.isArray(value) ? value : value ? [value] : [])
                    }
                >
                    <SelectTrigger
                        className="min-w-0 flex-1"
                        aria-invalid={error ? true : undefined}
                        data-attr="workflow-email-sender-select"
                    >
                        <SelectValue placeholder={rotation ? 'Choose senders' : 'Choose a sender'}>
                            {(value: string | string[] | null) => {
                                const ids = Array.isArray(value) ? value : value ? [value] : []
                                const labels = senders
                                    .filter((sender) => ids.includes(String(sender.id)))
                                    .map(senderLabel)
                                return labels.length ? (
                                    labels.join(', ')
                                ) : (
                                    <span className="text-muted-foreground">
                                        {rotation ? 'Choose senders' : 'Choose a sender'}
                                    </span>
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
                <Popover open={customOpen} onOpenChange={setCustomOpen}>
                    <PopoverTrigger
                        render={<Button variant="outline" />}
                        data-attr="email-from-custom-sender"
                        aria-label="Custom sender"
                    >
                        {custom || replyTo ? 'Edit sender' : 'Custom sender'}
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-96">
                        <EmailSenderForm
                            from={from}
                            replyTo={replyTo}
                            senders={senders}
                            variables={logicProps.variables}
                            dataAttrPrefix="workflow-email"
                            onChangeFrom={(next) => setEmailTemplateValue('from', next)}
                            onChangeReplyTo={(next) => setEmailTemplateValue('replyTo', next)}
                            onClear={clearCustomSender}
                            onDone={() => setCustomOpen(false)}
                            singleLine
                        />
                    </PopoverContent>
                </Popover>
            </div>
            {custom || replyTo ? (
                <Text size="xs" variant="muted" className="m-0 truncate">
                    {[custom && `Sends as ${custom}`, replyTo && `Replies go to ${replyTo}`]
                        .filter(Boolean)
                        .join(' · ')}
                </Text>
            ) : null}
        </HeaderField>
    )
}

function OptionalField({ field }: { field: OptionalHeaderField }): JSX.Element {
    const { emailTemplate, logicProps } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue, hideAdvancedField } = useActions(emailTemplaterLogic)
    const error = field.key === 'preheader' ? logicProps.fieldErrors?.preheader : undefined
    return (
        <HeaderField label={field.label} error={error}>
            <LiquidInput
                value={(emailTemplate as Record<string, any>)[field.key] ?? ''}
                onChange={(value) => setEmailTemplateValue(field.key, value ?? '')}
                invalid={!!error}
                trailing={
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Remove ${field.label}`}
                        onClick={() => {
                            setEmailTemplateValue(field.key, '')
                            hideAdvancedField(field.key)
                        }}
                    >
                        <IconX />
                    </Button>
                }
            />
        </HeaderField>
    )
}

/** The sender, recipient and subject, in the redesigned look. Optional fields come from one menu. */
export function QuillEmailHeaderFields(): JSX.Element {
    const { emailTemplate, logicProps, visibleFields } = useValues(emailTemplaterLogic)
    const { setEmailTemplateValue, revealAdvancedField } = useActions(emailTemplaterLogic)
    const supported = EMAIL_TYPE_SUPPORTED_FIELDS[logicProps.type]
    const optional = [...COPY_HEADER_FIELDS, PREHEADER_FIELD].filter(({ key }) =>
        supported.some((field) => field.key === key)
    )
    const shown = optional.filter(({ key }) => isHeaderFieldShown(visibleFields, key))
    const hidden = optional.filter(({ key }) => !isHeaderFieldShown(visibleFields, key))
    const errors = logicProps.fieldErrors

    return (
        <div data-quill className="flex flex-col gap-3 border-b p-3" data-attr="email-header-fields">
            <div className="grid grid-cols-1 gap-3 @lg:grid-cols-2">
                <SenderField />
                <HeaderField label="To" error={errors?.to}>
                    <LiquidInput
                        value={emailTemplate.to?.email ?? ''}
                        onChange={(email) => setEmailTemplateValue('to', { ...emailTemplate.to, email: email ?? '' })}
                        invalid={!!errors?.to}
                    />
                </HeaderField>
            </div>
            <HeaderField label="Subject" error={errors?.subject}>
                <LiquidInput
                    value={emailTemplate.subject ?? ''}
                    onChange={(subject) => setEmailTemplateValue('subject', subject ?? '')}
                    placeholder="What's this email about?"
                    invalid={!!errors?.subject}
                />
            </HeaderField>
            {shown.map((field) => (
                <OptionalField key={field.key} field={field} />
            ))}
            {hidden.length ? (
                <div>
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={<Button variant="ghost" size="sm" />}
                            data-attr="email-header-add-field"
                        >
                            <IconPlus />
                            Add field
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                            {hidden.map((field) => (
                                <DropdownMenuItem
                                    key={field.key}
                                    onClick={() => {
                                        revealAdvancedField(field.key)
                                        posthog.capture('email header field added', {
                                            field: field.key,
                                            editor_type: logicProps.type,
                                        })
                                    }}
                                    // pinned: data-attr values feed autocapture dashboards
                                    data-attr={`email-header-add-${field.key}`}
                                >
                                    {field.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            ) : null}
        </div>
    )
}
