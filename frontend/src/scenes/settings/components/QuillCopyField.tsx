import { type ReactNode, useId } from 'react'

import { IconCopy } from '@posthog/icons'
import {
    Field,
    FieldDescription,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
} from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function QuillCopyField({
    label,
    value,
    description,
    helpText,
    actions,
    sensitive = false,
    'data-attr': dataAttr,
}: {
    label: string
    value: string
    /** Names the value in the "copied" toast. */
    description?: string
    helpText?: ReactNode
    /** Extra `InputGroupButton`s shown after the copy button. */
    actions?: ReactNode
    sensitive?: boolean
    /** Set on the copy button. */
    'data-attr'?: string
}): JSX.Element {
    const id = useId()
    const copyLabel = `Copy ${label}`

    return (
        <Field>
            <FieldLabel htmlFor={id}>{label}</FieldLabel>
            <InputGroup>
                <InputGroupInput
                    id={id}
                    value={value}
                    readOnly
                    className={sensitive ? 'font-mono ph-no-capture' : 'font-mono'}
                />
                <InputGroupAddon align="inline-end">
                    <InputGroupButton
                        size="icon-xs"
                        aria-label={copyLabel}
                        tooltip={copyLabel}
                        onClick={() => void copyToClipboard(value, description)}
                        data-attr={dataAttr}
                    >
                        <IconCopy />
                    </InputGroupButton>
                    {actions}
                </InputGroupAddon>
            </InputGroup>
            {helpText ? <FieldDescription>{helpText}</FieldDescription> : null}
        </Field>
    )
}
