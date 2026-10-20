import { IOSection } from './IOSection'

export interface IOPanelProps {
    input: unknown
    output: unknown
}

export function IOPanel({ input, output }: IOPanelProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <IOSection title="Input" value={input} />
            <IOSection title="Output" value={output} />
        </div>
    )
}
