import { useId } from 'react'

import { Field, Input } from '@posthog/quill'

import type { ChartOptionTextInputProps } from './ChartOptionTextInput'
import { QuillChartOptionLabel } from './QuillChartOptionLabel'

export interface QuillChartOptionTextInputProps extends ChartOptionTextInputProps {
    draft: string
    setDraft: (draft: string) => void
    commit: () => void
}

export function QuillChartOptionTextInput({
    label,
    info,
    placeholder,
    draft,
    setDraft,
    commit,
    'data-attr': dataAttr,
}: QuillChartOptionTextInputProps): JSX.Element {
    const id = useId()

    return (
        <Field>
            {label && <QuillChartOptionLabel htmlFor={id} label={label} info={info} />}
            <Input
                id={id}
                value={draft}
                placeholder={placeholder}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                        commit()
                    }
                }}
                data-attr={dataAttr}
            />
        </Field>
    )
}
