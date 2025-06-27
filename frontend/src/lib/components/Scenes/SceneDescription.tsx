import { LemonButton } from "lib/lemon-ui/LemonButton/LemonButton"
import { LemonField } from "lib/lemon-ui/LemonField/LemonField"
import { TextareaPrimitive } from "lib/ui/TextareaPrimtive/TextareaPrimitive"
import { useEffect, useState } from "react"

type SceneDescriptionFormProps = {
    defaultValue: string
    isEditing: boolean
    onSave: (value: string) => void
    onCancel: () => void
}

export function SceneDescriptionForm({ defaultValue, isEditing, onSave, onCancel }: SceneDescriptionFormProps): JSX.Element {
    const [localValue, setLocalValue] = useState(defaultValue)
    const [localIsEditing, setLocalIsEditing] = useState(isEditing)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        onSave(localValue)
        setLocalIsEditing(false)
    }
    
    useEffect(() => {
        setLocalIsEditing(isEditing)
    }, [isEditing])

    return localIsEditing ? (
        <form onSubmit={handleSubmit} name="page-description">
            <LemonField.Pure label="Description" className="gap-0" htmlFor="description">
                <TextareaPrimitive
                    value={localValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                    placeholder="Description (optional)"
                    id="description"
                />
            </LemonField.Pure>
            <LemonButton type="primary" htmlType="submit">Save</LemonButton>
            <LemonButton type="secondary" htmlType="button" onClick={() => onCancel()}>Cancel</LemonButton>
        </form>
    ) : (
        <LemonField.Pure label="Description" className="gap-0">
            <p className="m-0">{defaultValue}</p>
        </LemonField.Pure>
    )
}