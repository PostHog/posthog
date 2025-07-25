import { IconCheck, IconX } from '@posthog/icons'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import {
    SelectPrimitive,
    SelectPrimitiveContent,
    SelectPrimitiveItem,
    SelectPrimitiveTrigger,
} from 'lib/ui/SelectPrimitive/SelectPrimitive'
import { useEffect, useState } from 'react'
import { SceneSelectProps as SceneSelectPropsBase } from './utils'

type SceneSelectProps = SceneSelectPropsBase & {
    buttonProps?: Omit<ButtonPrimitiveProps, 'children' | 'size'>
}

export function SceneSelect({
    onSave,
    dataAttrKey,
    name,
    canEdit = true,
    options,
    value,
    buttonProps,
}: SceneSelectProps): JSX.Element {
    const [localValue, setLocalValue] = useState(value || undefined)
    const [hasChanged, setHasChanged] = useState(false)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        localValue && onSave(localValue)
        setHasChanged(false)
    }

    useEffect(() => {
        setHasChanged(localValue !== value)
    }, [localValue, value])

    return (
        <form onSubmit={handleSubmit} name={`page-${name}-form`} className="flex flex-col gap-1">
            <div className="flex flex-col gap-0 ">
                <Label intent="menu" htmlFor={`page-${name}-select`}>
                    {name}
                </Label>
                <div className="-ml-1.5">
                    <SelectPrimitive
                        disabled={!canEdit || buttonProps?.disabled}
                        onValueChange={(value) => {
                            setLocalValue(value)
                        }}
                        value={localValue}
                    >
                        <SelectPrimitiveTrigger
                            buttonProps={{
                                ...buttonProps,
                                fullWidth: true,
                                tooltip: buttonProps?.tooltip,
                            }}
                        >
                            {options.find((option) => option.value === localValue)?.label || 'Select a value'}
                        </SelectPrimitiveTrigger>
                        <SelectPrimitiveContent matchTriggerWidth>
                            {options.map((option) => (
                                <SelectPrimitiveItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectPrimitiveItem>
                            ))}
                        </SelectPrimitiveContent>
                    </SelectPrimitive>
                </div>
            </div>
            {hasChanged && (
                <div className="flex gap-1">
                    <ButtonPrimitive
                        type="submit"
                        variant="outline"
                        disabled={!hasChanged}
                        tooltip={hasChanged ? `Update ${name}` : `No changes to update`}
                        data-attr={`${dataAttrKey}-${name}-update-button`}
                    >
                        <IconCheck />
                    </ButtonPrimitive>
                    <ButtonPrimitive
                        type="button"
                        variant="outline"
                        onClick={() => {
                            setLocalValue(value)
                        }}
                        tooltip="Cancel"
                        disabled={!hasChanged}
                    >
                        <IconX />
                    </ButtonPrimitive>
                </div>
            )}
        </form>
    )
}
