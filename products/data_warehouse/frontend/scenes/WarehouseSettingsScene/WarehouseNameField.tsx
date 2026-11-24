import { IconCheck, IconX } from '@posthog/icons'
import { Field, FieldDescription, FieldError, FieldLabel, Input, Spinner } from '@posthog/quill'

export interface WarehouseNameFieldProps {
    id: string
    label: string
    value: string
    onChange: (value: string) => void
    placeholder: string
    /** Whether the value passes the format rules. */
    valid: boolean
    /** Null while the availability is unknown. */
    available: boolean | null
    checking: boolean
    formatError: string
    unavailableError: string
    unknownError: string
    help: string
    disabled?: boolean
}

/** A name field with a format rule and a live availability check. */
export function WarehouseNameField({
    id,
    label,
    value,
    onChange,
    placeholder,
    valid,
    available,
    checking,
    formatError,
    unavailableError,
    unknownError,
    help,
    disabled,
}: WarehouseNameFieldProps): JSX.Element {
    const showFormatError = !!value && !valid
    const settled = !!value && valid && !checking
    const showAvailabilityError = settled && available !== true
    return (
        <Field>
            <FieldLabel htmlFor={id}>{label}</FieldLabel>
            <div className="flex items-center gap-2">
                <Input
                    id={id}
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder={placeholder}
                    disabled={disabled}
                    className="font-mono"
                />
                {!!value && valid && (checking ? <Spinner /> : available === true ? <IconCheck /> : <IconX />)}
            </div>
            {showFormatError ? (
                <FieldError>{formatError}</FieldError>
            ) : showAvailabilityError ? (
                <FieldError>{available === false ? unavailableError : unknownError}</FieldError>
            ) : (
                <FieldDescription>{help}</FieldDescription>
            )}
        </Field>
    )
}
