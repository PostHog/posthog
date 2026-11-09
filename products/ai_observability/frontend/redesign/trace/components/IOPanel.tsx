import { IOSection } from './IOSection'

export interface IOPanelProps {
    input: unknown
    output: unknown
    highlightQuery?: string | null
}

export function IOPanel({ input, output, highlightQuery = null }: IOPanelProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <IOSection title="Input" value={input} highlightQuery={highlightQuery} />
            <IOSection title="Output" value={output} highlightQuery={highlightQuery} />
        </div>
    )
}
