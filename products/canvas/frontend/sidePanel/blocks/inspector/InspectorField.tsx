import { ReactNode, useId } from 'react'

import { Field, FieldDescription, FieldTitle } from '@posthog/quill'

/** A labeled inspector control, with an optional hint under it. */
export function InspectorField({
    label,
    hint,
    children,
}: {
    label: string
    hint?: ReactNode
    children: ReactNode
}): JSX.Element {
    // Controls here name themselves with aria-label, so the title only labels the group.
    const titleId = useId()
    return (
        <Field aria-labelledby={titleId}>
            <FieldTitle id={titleId}>{label}</FieldTitle>
            {children}
            {hint ? <FieldDescription>{hint}</FieldDescription> : null}
        </Field>
    )
}
