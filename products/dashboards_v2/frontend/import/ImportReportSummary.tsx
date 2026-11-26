import type { ImportReport, ImportRequirements } from './importReport'
import { tileCounts } from './importReport'

const SOURCE_NAMES: Record<ImportReport['source'], string> = {
    grafana: 'Grafana',
    'grafana-v2': 'Grafana 12',
    newrelic: 'New Relic',
}

const REQUIREMENT_NAMES: Record<keyof ImportRequirements, string> = {
    events: 'Events',
    properties: 'Properties',
    metrics: 'Metrics',
    logStreams: 'Log streams',
}

const plural = (count: number, one: string, many: string): string => `${count} ${count === 1 ? one : many}`

export function ImportReportSummary({ report }: { report: ImportReport }): JSX.Element {
    const counts = tileCounts(report)
    const attention = report.tiles.filter((tile) => tile.status !== 'mapped')
    const requirements = (Object.keys(REQUIREMENT_NAMES) as (keyof ImportRequirements)[]).filter(
        (kind) => report.requires[kind].length > 0
    )
    return (
        <div className="flex flex-col gap-3 text-sm" data-attr="dashboard-v2-import-report">
            <p className="m-0">
                {SOURCE_NAMES[report.source]} dashboard: {plural(counts.mapped, 'tile', 'tiles')} mapped,{' '}
                {counts.partial} partly mapped, {counts.unsupported} not supported.{' '}
                {report.queries.total > 0 && (
                    <span>
                        {report.queries.translated} of {plural(report.queries.total, 'query', 'queries')} can run as
                        they are.
                    </span>
                )}
            </p>
            {requirements.length > 0 && (
                <section className="flex flex-col gap-1">
                    <h3 className="text-sm font-semibold m-0">Data this board reads</h3>
                    {requirements.map((kind) => (
                        <p key={kind} className="m-0 text-muted-foreground break-words">
                            {REQUIREMENT_NAMES[kind]} ({report.requires[kind].length}):{' '}
                            {report.requires[kind].join(', ')}
                        </p>
                    ))}
                </section>
            )}
            {report.notes.length > 0 && (
                <section className="flex flex-col gap-1">
                    <h3 className="text-sm font-semibold m-0">About the whole board</h3>
                    <ul className="m-0 pl-4 list-disc">
                        {report.notes.map((note) => (
                            <li key={note}>{note}</li>
                        ))}
                    </ul>
                </section>
            )}
            {attention.length > 0 && (
                <section className="flex flex-col gap-1">
                    <h3 className="text-sm font-semibold m-0">Tiles to check</h3>
                    <ul className="m-0 pl-4 list-disc">
                        {attention.map((tile) => (
                            <li key={tile.tileId}>
                                <span className="font-medium">{tile.title || tile.from}</span>
                                {tile.status === 'unsupported' ? ' (shown as a note)' : ''}: {tile.reasons.join(' ')}
                            </li>
                        ))}
                    </ul>
                </section>
            )}
        </div>
    )
}
