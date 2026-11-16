import { EditableField } from 'lib/components/EditableField/EditableField'

export function DashboardTileGroupDescription({
    description,
    onChange,
}: {
    description?: string
    onChange?: (description: string) => void
}): JSX.Element | null {
    if (!description && !onChange) {
        return null
    }
    return (
        <div className="mb-3 whitespace-pre-wrap text-secondary text-sm" data-not-quill>
            {onChange ? (
                <EditableField
                    name="group description"
                    value={description ?? ''}
                    onSave={onChange}
                    placeholder="Add a description"
                    maxLength={4000}
                    multiline
                    compactButtons
                />
            ) : (
                description
            )}
        </div>
    )
}
