import { LemonButton } from "lib/lemon-ui/LemonButton/LemonButton"
import { LemonField } from "lib/lemon-ui/LemonField/LemonField"
import { TextareaPrimitive } from "lib/ui/TextareaPrimtive/TextareaPrimitive"
import { useState } from "react"

type SceneDescriptionFormProps = {
    defaultValue: string
    canEdit: boolean
    onSave: (value: string) => void
}

export function SceneDescriptionForm({ defaultValue, canEdit, onSave }: SceneDescriptionFormProps): JSX.Element {
    const [localValue, setLocalValue] = useState(defaultValue)
    const [isEditing, setIsEditing] = useState(false)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        onSave(localValue)
    }

    return canEdit && isEditing ? (
        <form onSubmit={handleSubmit} name="page-description">
            <LemonField.Pure label="Description" className="gap-0" htmlFor="description">
                <TextareaPrimitive
                    value={defaultValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                />
            </LemonField.Pure>
            <LemonButton type="primary" htmlType="submit">Save</LemonButton>
            <LemonButton type="secondary" htmlType="button" onClick={() => setIsEditing(false)}>Cancel</LemonButton>
        </form>
    ) : (
        <LemonField.Pure label="Description" className="gap-0">
            <p className="m-0">{defaultValue}</p>
        </LemonField.Pure>
    )
}