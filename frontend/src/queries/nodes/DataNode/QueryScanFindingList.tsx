import { QueryScanWarning } from '~/queries/schema/schema-general'

/** A finding marks SQL with backticks, the way the assistant reads it. */
function withInlineCode(message: string): JSX.Element {
    return (
        <>
            {message
                .split('`')
                .map((part, index) =>
                    index % 2 === 1 ? <code key={index}>{part}</code> : <span key={index}>{part}</span>
                )}
        </>
    )
}

export function QueryScanFindingList({ findings }: { findings: QueryScanWarning[] }): JSX.Element {
    return (
        <ul className="list-disc pl-5">
            {findings.map((finding, index) => (
                <li key={`${finding.kind}-${index}`}>{withInlineCode(finding.message)}</li>
            ))}
        </ul>
    )
}
