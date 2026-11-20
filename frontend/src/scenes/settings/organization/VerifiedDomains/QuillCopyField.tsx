import { useId } from 'react'

import { IconCopy } from '@posthog/icons'
import { Field, FieldLabel, InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function QuillCopyField({
    label,
    value,
    description,
    sensitive = false,
}: {
    label: string
    value: string
    /** Names the value in the "copied" toast. */
    description?: string
    sensitive?: boolean
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
                    >
                        <IconCopy />
                    </InputGroupButton>
                </InputGroupAddon>
            </InputGroup>
        </Field>
    )
}
