import { MessageMarkdown } from './MessageMarkdown'

export interface ThinkingPartProps {
    text: string
}

export function ThinkingPart({ text }: ThinkingPartProps): JSX.Element {
    return (
        <details className="text-secondary">
            <summary className="cursor-pointer text-xs font-semibold">Thinking</summary>
            <MessageMarkdown text={text} className="ph-no-capture mt-1" />
        </details>
    )
}
