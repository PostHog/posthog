import { useValues } from 'kea'

import { LemonBanner, LemonTag, LemonTagType, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { pluralize } from 'lib/utils/strings'

import type { AdjustedRunApi } from '../generated/api.schemas'
import { metricUsageLogic } from '../metricUsageLogic'

const FETCH_OUTCOMES: Record<string, { label: string; type: LemonTagType }> = {
    adapted: { label: 'Adapted', type: 'success' },
    missed: { label: 'Missed', type: 'warning' },
    silent: { label: 'Silent', type: 'danger' },
}

export function MetricUsageTab({ name }: { name: string }): JSX.Element {
    const { usage, usageLoadFailed } = useValues(metricUsageLogic({ name }))

    if (usageLoadFailed) {
        return (
            <LemonBanner type="error">
                Couldn't load this metric's usage. Refresh the page, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (usage === null) {
        return <Spinner />
    }
    if (usage === 'none') {
        return <p className="m-0">No usage scan has finished yet. A scan runs every week.</p>
    }

    const directRuns = Object.entries(usage.runs?.direct_runs ?? {}).sort((a, b) => b[1] - a[1])
    const columns: LemonTableColumns<AdjustedRunApi> = [
        {
            title: 'Question',
            key: 'intent',
            render: (_, run) => <span className="line-clamp-2 min-w-48">{run.intent || 'No question recorded'}</span>,
        },
        {
            title: 'How the agent got there',
            key: 'fetch_outcome',
            render: (_, run) => {
                const outcome = FETCH_OUTCOMES[run.fetch_outcome] ?? {
                    label: run.fetch_outcome,
                    type: 'default' as const,
                }
                return (
                    <div className="flex flex-wrap gap-1">
                        <LemonTag type={outcome.type}>{outcome.label}</LemonTag>
                        {run.relation === 'slice' && <LemonTag>With a filter</LemonTag>}
                        {run.is_scout && <LemonTag>Scout</LemonTag>}
                    </div>
                )
            },
        },
        { title: 'When', key: 'occurred_at', render: (_, run) => <TZLabel time={run.occurred_at} /> },
    ]

    return (
        <div className="flex flex-col gap-4">
            <span className="text-secondary">
                Usage from <TZLabel time={usage.window_start} /> to <TZLabel time={usage.window_end} />
            </span>
            {usage.failed_sections.length > 0 && (
                <LemonBanner type="warning">
                    <div>
                        Part of the last scan failed, so some of these counts are missing. Run a new scan from the
                        catalog's usage tab to try again.
                    </div>
                    {usage.failed_sections.map((failure) => (
                        <div key={failure.section} className="text-xs">
                            {failure.reason}
                        </div>
                    ))}
                </LemonBanner>
            )}
            <div className="flex flex-wrap gap-x-8 gap-y-2">
                <div className="flex flex-col">
                    <span className="text-secondary text-xs">Agent runs</span>
                    <div className="flex flex-wrap items-center gap-1">
                        <span className="text-lg font-semibold">
                            {directRuns.reduce((total, [, runs]) => total + runs, 0)}
                        </span>
                        {directRuns.map(([surface, runs]) => (
                            <LemonTag key={surface} size="small">
                                {surface} {runs}
                            </LemonTag>
                        ))}
                    </div>
                </div>
                <div className="flex flex-col">
                    <span className="text-secondary text-xs">Agent re-derivations</span>
                    <span className="text-lg font-semibold">
                        {usage.adjusted.adapted} adapted, {usage.adjusted.missed} missed, {usage.adjusted.silent} silent
                    </span>
                </div>
                <div className="flex flex-col">
                    <span className="text-secondary text-xs">Scouts</span>
                    <span className="text-lg font-semibold">
                        {pluralize(usage.runs?.scout_runs ?? 0, 'run')},{' '}
                        {pluralize(
                            usage.scout_adjusted.adapted + usage.scout_adjusted.missed + usage.scout_adjusted.silent,
                            're-derivation'
                        )}
                    </span>
                </div>
            </div>
            <LemonTable
                columns={columns}
                dataSource={usage.adjusted_runs}
                rowKey={(run) => `${run.occurred_at}-${run.session_id}-${run.sql.length}`}
                size="small"
                emptyState="No agent computed this metric in its own SQL in this window."
                expandable={{
                    expandedRowRender: (run) => (
                        <div className="flex flex-col gap-2 p-2">
                            <p className="m-0">{run.reasoning}</p>
                            <CodeSnippet language={Language.SQL} wrap>
                                {run.sql}
                            </CodeSnippet>
                        </div>
                    ),
                }}
                data-attr="data-catalog-metric-usage-runs"
            />
        </div>
    )
}
