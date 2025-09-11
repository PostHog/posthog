import { IconCheck, IconLoading, IconX } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SelectPrimitiveItemProps } from 'lib/ui/SelectPrimitive/SelectPrimitive'

export type SceneCanEditProps = {
    canEdit?: boolean
}

export type SceneLoadingProps = {
    isLoading?: boolean
}

export type SceneDataAttrKeyProps = {
    dataAttrKey: string
}

export type SceneNameProps = {
    name: string
}

// Common props for all scene inputs
export type SceneTextInputProps = SceneCanEditProps &
    SceneDataAttrKeyProps &
    SceneNameProps &
    SceneLoadingProps & {
        defaultValue?: string
        onSave: (value: string) => void
        optional?: boolean
    }

export type SceneTextareaProps = SceneTextInputProps & {
    markdown?: boolean
}

export type SceneInputProps = SceneCanEditProps &
    SceneDataAttrKeyProps &
    SceneDataAttrKeyProps &
    SceneLoadingProps & {
        defaultValue?: string
        onSave: (value: string) => void
        optional?: boolean
    }

export type SceneSaveCancelButtonsProps = SceneDataAttrKeyProps &
    SceneNameProps &
    SceneLoadingProps & {
        onCancel: () => void
        hasChanged: boolean
        error?: string | null
    }

export type SceneSelectProps = SceneInputProps &
    SceneNameProps & {
        options: SelectPrimitiveItemProps[]
        value?: string
    }

export function SceneSaveCancelButtons({
    name,
    onCancel,
    isLoading,
    hasChanged,
    error,
    dataAttrKey,
}: SceneSaveCancelButtonsProps): JSX.Element {
    return (
        <div className="flex gap-1">
            <ButtonPrimitive
                type="submit"
                variant="outline"
                disabled={!hasChanged || !!error}
                tooltip={hasChanged ? `Update ${dataAttrKey}` : 'No changes to update'}
                data-attr={`${dataAttrKey}-${name}-update-button`}
                aria-label={hasChanged ? `Update ${name}` : 'No changes to update'}
            >
                {isLoading ? <IconLoading /> : <IconCheck />}
            </ButtonPrimitive>
            <ButtonPrimitive
                type="button"
                variant="outline"
                onClick={onCancel}
                tooltip="Cancel"
                aria-label={`Cancel ${name}`}
                data-attr={`${dataAttrKey}-${name}-cancel-button`}
            >
                <IconX />
            </ButtonPrimitive>
        </div>
    )
}
