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
