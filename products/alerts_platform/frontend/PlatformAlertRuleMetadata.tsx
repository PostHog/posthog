import { PlatformAlertConfigurationApi } from './generated/api.schemas'

export function PlatformAlertRuleMetadata({
    configuration,
}: {
    configuration: PlatformAlertConfigurationApi
}): JSX.Element {
    const groups: [string, Record<string, string>][] = [
        ['Labels', configuration.labels],
        ['Annotations', configuration.annotations],
    ]
    if (groups.every(([, entries]) => Object.keys(entries).length === 0)) {
        return <p className="m-0 text-secondary">No labels or annotations yet.</p>
    }
    return (
        <div className="flex flex-col gap-4">
            {groups.map(([title, entries]) => (
                <div key={title} className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold m-0">{title}</h3>
                    {Object.keys(entries).length === 0 ? (
                        <p className="m-0 text-secondary">None</p>
                    ) : (
                        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 m-0" translate="no">
                            {Object.entries(entries).map(([name, value]) => (
                                <div key={name} className="contents">
                                    <dt className="font-mono text-secondary break-all">{name}</dt>
                                    <dd className="m-0 break-all">{value}</dd>
                                </div>
                            ))}
                        </dl>
                    )}
                </div>
            ))}
        </div>
    )
}
