import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

export function TextPanel({ markdown }: { markdown: string }): JSX.Element {
    return (
        <div className="h-full overflow-auto">
            <LemonMarkdown>{markdown}</LemonMarkdown>
        </div>
    )
}
