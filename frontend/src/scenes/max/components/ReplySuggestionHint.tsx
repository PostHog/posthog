export function ReplySuggestionHint({
    suggestion,
    keyHint,
}: {
    suggestion: string
    keyHint: JSX.Element
}): JSX.Element {
    return (
        <span className="text-sm whitespace-pre-wrap break-words" data-attr="max-reply-suggestion">
            {suggestion}
            <span className="ml-2 inline-flex items-center gap-1 align-middle text-xs whitespace-nowrap">
                {keyHint}
                <span>to accept</span>
            </span>
        </span>
    )
}
