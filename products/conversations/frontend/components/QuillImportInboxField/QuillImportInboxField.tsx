import { useId } from 'react'

import {
    Field,
    FieldDescription,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

export function QuillImportInboxField({
    label,
    description,
    noneLabel,
    placeholder,
    emailConfigs,
    value,
    onChange,
    disabledReason,
}: {
    label: string
    description: string
    noneLabel: string
    placeholder: string
    emailConfigs: { id: string; from_email: string }[]
    value: string | null
    onChange: (value: string | null) => void
    disabledReason: string | undefined
}): JSX.Element {
    const id = useId()
    const options = [
        { label: noneLabel, value: null },
        ...emailConfigs.map((config) => ({ label: config.from_email, value: config.id })),
    ]

    return (
        <Field>
            <FieldLabel htmlFor={id}>{label}</FieldLabel>
            <Select<string | null> items={options} value={value} onValueChange={onChange}>
                <SelectTrigger id={id} className="w-full" disabledReason={disabledReason}>
                    <SelectValue placeholder={placeholder} />
                </SelectTrigger>
                <SelectContent>
                    {options.map((option) => (
                        <SelectItem key={option.value ?? 'none'} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <FieldDescription>{description}</FieldDescription>
        </Field>
    )
}
