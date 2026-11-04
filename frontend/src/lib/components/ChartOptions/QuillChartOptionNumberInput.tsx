import { useId } from 'react'

import { Field, FieldDescription, InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill'

import type { ChartOptionNumberInputProps } from './ChartOptionNumberInput'
import { QuillChartOptionLabel } from './QuillChartOptionLabel'

export interface QuillChartOptionNumberInputProps extends ChartOptionNumberInputProps {
    draft: string
    setDraft: (draft: string) => void
    commit: () => void
}

export function QuillChartOptionNumberInput({
    label,
    info,
    suffix,
    placeholder,
    disabledReason,
    draft,
    setDraft,
    commit,
    'data-attr': dataAttr,
}: QuillChartOptionNumberInputProps): JSX.Element {
    const id = useId()
    const disabled = !!disabledReason

    return (
        <Field data-disabled={disabled || undefined}>
            <div className="flex items-center justify-between gap-2">
                <QuillChartOptionLabel htmlFor={id} label={label} info={info} />
                <InputGroup className="w-28" aria-disabled={disabled || undefined}>
                    <InputGroupInput
                        id={id}
                        // Text, not a number input: a number input reports "-" as empty while typing "-10".
                        type="text"
                        inputMode="decimal"
                        value={draft}
                        placeholder={placeholder}
                        disabled={disabled}
                        onChange={(event) => setDraft(event.target.value)}
                        onBlur={commit}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                commit()
                            }
                        }}
                        data-attr={dataAttr}
                    />
                    {suffix && (
                        <InputGroupAddon align="inline-end">
                            <InputGroupText>{suffix}</InputGroupText>
                        </InputGroupAddon>
                    )}
                </InputGroup>
            </div>
            {/* An input has no disabledReason, so the reason sits under it instead of in a tooltip. */}
            {disabledReason && <FieldDescription>{disabledReason}</FieldDescription>}
        </Field>
    )
}
