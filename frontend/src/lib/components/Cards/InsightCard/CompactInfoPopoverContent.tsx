import { EditableField } from 'lib/components/EditableField/EditableField'

export interface CompactInfoPopoverContentProps {
    popoverTopHeading?: JSX.Element | null
    metaTitle: string
    metaDescription?: JSX.Element | null
    metaDescriptionText: string
    onMetaSave?: (updates: { name?: string; description?: string }) => void
    metaDetails?: JSX.Element | null
}

export function CompactInfoPopoverContent({
    popoverTopHeading,
    metaTitle,
    metaDescription,
    metaDescriptionText,
    onMetaSave,
    metaDetails,
}: CompactInfoPopoverContentProps): JSX.Element {
    return (
        <div
            className="p-4 max-w-md space-y-3"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
            }}
        >
            {popoverTopHeading && (
                <h5 className="uppercase text-xs font-bold text-muted tracking-wide m-0">{popoverTopHeading}</h5>
            )}
            {onMetaSave ? (
                <>
                    <EditableField
                        name="title"
                        value={metaTitle || ''}
                        onSave={(value) => onMetaSave({ name: value })}
                        placeholder="Untitled"
                        saveOnBlur
                        clickToEdit
                        compactButtons
                        compactIcon
                        className="font-semibold text-sm mt-1"
                        data-attr="insight-card-title"
                    />
                    <EditableField
                        name="description"
                        value={metaDescriptionText || ''}
                        onSave={(value) => onMetaSave({ description: value })}
                        placeholder="Enter description (optional)"
                        saveOnBlur
                        clickToEdit
                        multiline
                        markdown
                        compactButtons
                        compactIcon
                        className="text-xs w-full"
                        data-attr="insight-card-description"
                    />
                </>
            ) : (
                <>
                    {metaTitle && <p className="font-semibold m-0">{metaTitle}</p>}
                    {metaDescription}
                </>
            )}
            {metaDetails}
        </div>
    )
}
