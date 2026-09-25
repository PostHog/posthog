import { TZLabel } from 'lib/components/TZLabel'

import { NodeProperties } from '../types'

export interface NodePropertyListProps {
    properties: NodeProperties
}

export function NodePropertyList({ properties }: NodePropertyListProps): JSX.Element {
    const prompt =
        properties.promptName && properties.promptVersion !== null
            ? `${properties.promptName} v${properties.promptVersion}`
            : properties.promptName
    const rows: [string, string | null][] = [
        ['Model', properties.model],
        ['Provider', properties.provider],
        ['Temperature', properties.temperature !== null ? String(properties.temperature) : null],
        ['Prompt', prompt],
        ['Session', properties.sessionId],
    ]
    return (
        <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-8 gap-y-2 text-sm">
            <dt className="text-secondary">Time</dt>
            <dd className="m-0">
                <TZLabel time={properties.timestamp} timestampStyle="absolute" showSeconds />
            </dd>
            {rows
                .filter((row): row is [string, string] => row[1] !== null)
                .map(([label, value]) => (
                    <div key={label} className="contents">
                        <dt className="text-secondary">{label}</dt>
                        <dd className="m-0 font-mono text-xs break-all">{value}</dd>
                    </div>
                ))}
        </dl>
    )
}
