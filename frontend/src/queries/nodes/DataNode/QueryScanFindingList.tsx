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

export interface QueryScanFindingListProps {
    findings: QueryScanWarning[]
    /** Drops the bullet for a single finding. Only where a sibling icon already marks it, e.g. inside a LemonBanner. */
    dropBulletIfSingle?: boolean
}

export function QueryScanFindingList({ findings, dropBulletIfSingle }: QueryScanFindingListProps): JSX.Element {
    if (dropBulletIfSingle && findings.length === 1) {
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
