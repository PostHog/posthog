import { ReactNode } from 'react'

import { Field, FieldContent, FieldDescription, FieldLabel, FieldTitle } from '@posthog/quill'

export interface SceneSettingsRowProps {
    label: ReactNode
    description?: ReactNode
    htmlFor?: string
    children: ReactNode
    dataAttr?: string
}

export function SceneSettingsRow({
    label,
    description,
    htmlFor,
    children,
    dataAttr,
}: SceneSettingsRowProps): JSX.Element {
    return (
        <Field
            className="grid grid-cols-1 gap-x-6 gap-y-2 px-4 py-3 @lg/settings-card:grid-cols-3"
            data-attr={dataAttr}
        >
            <FieldContent>
                {htmlFor ? <FieldLabel htmlFor={htmlFor}>{label}</FieldLabel> : <FieldTitle>{label}</FieldTitle>}
                {description && <FieldDescription>{description}</FieldDescription>}
            </FieldContent>
            <div className="flex min-w-0 flex-wrap items-center gap-2 @lg/settings-card:col-span-2">{children}</div>
        </Field>
    )
}
