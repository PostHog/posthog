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
    // A single finding already reads as one message next to the banner's own icon;
    // a bullet in front of it just doubles the marker.
    if (findings.length === 1) {
        return <div>{withInlineCode(findings[0].message)}</div>
    }

    return (
        <ul className="list-disc pl-5">
            {findings.map((finding, index) => (
                <li key={`${finding.kind}-${index}`}>{withInlineCode(finding.message)}</li>
            ))}
        </ul>
    )
}
