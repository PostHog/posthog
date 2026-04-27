type MarkdownEditorCharacterCountFooterProps = {
    currentLength: number
    maxLength: number
}

export function MarkdownEditorCharacterCountFooter({
    currentLength,
    maxLength,
}: MarkdownEditorCharacterCountFooterProps): JSX.Element {
    const isAtCharacterLimit = currentLength > maxLength

    return (
        <div
            className={`px-3 py-1 border-t bg-surface-primary text-xs text-right shrink-0 ${
                isAtCharacterLimit ? 'text-danger' : 'text-muted'
            }`}
        >
            {currentLength}/{maxLength} characters
            {isAtCharacterLimit ? ' (limit reached)' : ''}
        </div>
    )
}
