import { useEffect, useState } from 'react'

import { ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import {
    SelectPrimitive,
    SelectPrimitiveContent,
    SelectPrimitiveItem,
    SelectPrimitiveTrigger,
} from 'lib/ui/SelectPrimitive/SelectPrimitive'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { SceneSaveCancelButtons, SceneSelectProps as SceneSelectPropsBase } from './utils'

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
            <ScenePanelLabel htmlFor={`page-${name}-select`} title={name}>
                <SelectPrimitive
                    disabled={!canEdit || buttonProps?.disabled}
                    onValueChange={(value) => {
                        setLocalValue(value)
                    }}
                    defaultValue={localValue}
                    value={localValue}
                >
                    <SelectPrimitiveTrigger
                        buttonProps={{
                            ...buttonProps,
                            fullWidth: true,
                            tooltip: buttonProps?.tooltip,
                            variant: 'panel',
                        }}
                    >
                        {options.find((option) => option.value === localValue)?.label || 'Select a value'}
                    </SelectPrimitiveTrigger>
                    <SelectPrimitiveContent matchTriggerWidth>
                        {options.map((option) => (
                            <SelectPrimitiveItem key={option.value} {...option}>
                                {option.label}
                            </SelectPrimitiveItem>
                        ))}
                    </SelectPrimitiveContent>
                </SelectPrimitive>
            </ScenePanelLabel>

            {hasChanged && (
                <SceneSaveCancelButtons
                    name={name}
                    onCancel={() => {
                        setLocalValue(value)
                    }}
                    hasChanged={hasChanged}
                    dataAttrKey={dataAttrKey}
                />
            )}
        </form>
    )
}
