import { useId } from 'react'

import { Button, Field, FieldContent, FieldDescription, FieldLabel, RadioGroup, RadioGroupItem } from '@posthog/quill'

import { LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

export function QuillTeamSettingRadio<T extends string>({
    options,
    value,
    onValueChange,
    onSave,
    saveDisabledReason,
}: {
    options: LemonRadioOption<T>[]
    value: T
    onValueChange: (value: T) => void
    onSave: () => void
    saveDisabledReason?: string | null
}): JSX.Element {
    const idPrefix = useId()

    return (
        <div className="flex flex-col gap-4">
            <RadioGroup value={value} onValueChange={(next) => onValueChange(next as T)} className="w-fit">
                {options.map((option) => {
                    const optionId = `${idPrefix}-${option.value}`

                    return (
                        <Field key={option.value} orientation="horizontal">
                            <RadioGroupItem
                                id={optionId}
                                value={option.value}
                                disabledReason={option.disabledReason}
                                data-attr={option['data-attr']}
                                aria-label={option['aria-label']}
                            />
                            <FieldContent>
                                <FieldLabel htmlFor={optionId}>
                                    {/* Some callers pass a label with a second line of muted text inside it. */}
                                    <span className="flex flex-col">{option.label}</span>
                                </FieldLabel>
                                {option.description && <FieldDescription>{option.description}</FieldDescription>}
                            </FieldContent>
                        </Field>
                    )
                })}
            </RadioGroup>
            <div>
                <Button variant="primary" onClick={onSave} disabledReason={saveDisabledReason}>
                    Save
                </Button>
            </div>
        </div>
    )
}
