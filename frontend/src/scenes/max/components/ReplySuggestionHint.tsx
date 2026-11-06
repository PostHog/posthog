export function ReplySuggestionHint({
    suggestion,
    acceptHint,
}: {
    suggestion: string
    acceptHint: JSX.Element
}): JSX.Element {
    return (
        <span className="text-sm whitespace-pre-wrap break-words" data-attr="max-reply-suggestion">
            {suggestion}
            <span className="ml-2 inline-flex align-middle whitespace-nowrap">{acceptHint}</span>
        </span>
    )
}
