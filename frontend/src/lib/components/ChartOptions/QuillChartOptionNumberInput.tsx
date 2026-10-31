import { useId } from 'react'

import { Field, FieldDescription, InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill'

import type { ChartOptionNumberInputProps } from './ChartOptionNumberInput'
import { QuillChartOptionLabel } from './QuillChartOptionLabel'

export interface QuillChartOptionNumberInputProps extends ChartOptionNumberInputProps {
    draft: number | undefined
    setDraft: (draft: number | undefined) => void
    commit: () => void
}

export function QuillChartOptionNumberInput({
    label,
    info,
    min,
    max,
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
                        type="number"
                        value={draft ?? ''}
                        min={min}
                        max={max}
                        step={1}
                        placeholder={placeholder}
                        disabled={disabled}
                        onChange={(event) => {
                            const next = event.target.valueAsNumber
                            setDraft(Number.isFinite(next) ? next : undefined)
                        }}
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
