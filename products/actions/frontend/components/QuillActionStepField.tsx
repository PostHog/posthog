import { useId } from 'react'

import { IconX } from '@posthog/icons'
import {
    Field,
    FieldDescription,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
} from '@posthog/quill'

/** A text field of a match group, such as the page URL, with an optional control beside its label. */
export function QuillActionStepField({
    label,
    labelExtra,
    caption,
    hint,
    value,
    onChange,
    placeholder = 'Specify a value to match on this',
    disabledReason,
    dataAttr = 'edit-action-url-input',
}: {
    label: string
    labelExtra?: JSX.Element
    caption?: React.ReactNode
    /** Shown under the input, for example how the chosen matching treats the value. */
    hint?: React.ReactNode
    value: string
    onChange: (value: string) => void
    placeholder?: string
    disabledReason?: string
    dataAttr?: string
}): JSX.Element {
    const id = useId()

    return (
        <Field>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <FieldLabel htmlFor={id}>{label}</FieldLabel>
                {labelExtra}
            </div>
            {caption && <FieldDescription>{caption}</FieldDescription>}
            <InputGroup>
                <InputGroupInput
                    id={id}
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder={placeholder}
                    disabledReason={disabledReason}
                    data-attr={dataAttr}
                />
                {value !== '' && !disabledReason && (
                    <InputGroupAddon align="inline-end">
                        <InputGroupButton size="icon-xs" aria-label={`Clear ${label}`} onClick={() => onChange('')}>
                            <IconX />
                        </InputGroupButton>
                    </InputGroupAddon>
                )}
            </InputGroup>
            {hint && <FieldDescription>{hint}</FieldDescription>}
        </Field>
    )
}
