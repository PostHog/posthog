import { Badge, Checkbox, Field, FieldContent, FieldDescription, FieldLabel } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

export function QuillNotificationCheckbox({
    id,
    label,
    tag,
    description,
    checked,
    indeterminate,
    onCheckedChange,
    disabled,
    disabledReason,
    lockedByAdmin = false,
    dataAttr,
    className,
}: {
    id: string
    label: string
    /** Muted badge after the label, such as a project id or a pipeline kind. */
    tag?: string
    description?: string
    checked: boolean
    indeterminate?: boolean
    onCheckedChange: (checked: boolean) => void
    disabled?: boolean
    disabledReason?: string
    lockedByAdmin?: boolean
    dataAttr?: string
    className?: string
}): JSX.Element {
    return (
        <Field orientation="horizontal" className={cn('w-fit', className)}>
            <Checkbox
                id={id}
                checked={checked}
                indeterminate={indeterminate}
                onCheckedChange={onCheckedChange}
                disabled={disabled}
                disabledReason={disabledReason}
                data-attr={dataAttr}
            />
            <FieldContent>
                <FieldLabel htmlFor={id}>
                    <span className="flex flex-wrap items-center gap-2">
                        {label}
                        {tag && <Badge>{tag}</Badge>}
                        {lockedByAdmin && <Badge variant="info">Set by your admin</Badge>}
                    </span>
                </FieldLabel>
                {description && <FieldDescription>{description}</FieldDescription>}
            </FieldContent>
        </Field>
    )
}
