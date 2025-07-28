import { IconCheck, IconLoading, IconX } from '@posthog/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

export type SceneCanEditProps = {
    canEdit?: boolean
}

export type SceneLoadingProps = {
    isLoading?: boolean
}

export type SceneDataAttrKeyProps = {
    dataAttrKey: string
}

// Common props for all scene inputs
export type SceneInputProps = SceneCanEditProps &
    SceneDataAttrKeyProps &
    SceneLoadingProps & {
        defaultValue: string
        onSave: (value: string) => void
        optional?: boolean
    }

export type SceneSaveCancelButtonsProps = SceneDataAttrKeyProps &
    SceneLoadingProps & {
        onCancel: () => void
        hasChanged: boolean
        error?: string | null
        name: string
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
        <div className="flex gap-1 px-button-padding-x">
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
