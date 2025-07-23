export type SceneCanEditProps = {
    canEdit?: boolean
}

export type SceneDataAttrKeyProps = {
    dataAttrKey: string
}

// Common props for all scene inputs
export type SceneInputProps = SceneCanEditProps &
    SceneDataAttrKeyProps & {
        defaultValue: string
        onSave: (value: string) => void
        optional?: boolean
    }
