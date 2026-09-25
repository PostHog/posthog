export interface ThinkingPartProps {
    text: string
}

export function ThinkingPart({ text }: ThinkingPartProps): JSX.Element {
    return (
        <details className="text-secondary">
            <summary className="cursor-pointer text-xs font-semibold">Thinking</summary>
            <p className="m-0 mt-1 whitespace-pre-wrap break-words text-sm">{text}</p>
        </details>
    )
}
