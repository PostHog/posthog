import { useValues } from 'kea'

import { LemonBanner, LemonTag, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { AdjustedRunApi, UsageSectionEnumApi } from '../generated/api.schemas'
import { metricUsageLogic } from '../metricUsageLogic'
import { agentSurfaceLabel, surfaceRuns } from '../usageRows'

const UNAVAILABLE = 'Unavailable'
// The metric endpoint returns only the failures of these two sections.
const SECTION_LABELS: Partial<Record<UsageSectionEnumApi, string>> = {
    metric_runs: 'run counts',
    adjusted_runs: 're-derivations',
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

    const directRuns = surfaceRuns(usage.runs?.direct_runs ?? {})
    const scoutRederivations = usage.adjusted_runs.filter((run) => run.is_scout).length
    // A failed section returns no rows, so its counts show as unavailable instead of zero.
    const failedSections = new Set(usage.failed_sections.map((failure) => failure.section))
    const runsFailed = failedSections.has('metric_runs')
    const rederivationsFailed = failedSections.has('adjusted_runs')
    const columns: LemonTableColumns<AdjustedRunApi> = [
        {
            title: 'Question',
            key: 'intent',
            render: (_, run) => (
                <div className="flex min-w-48 flex-col gap-1 py-1">
                    <span className="line-clamp-2">{run.intent || 'No question recorded'}</span>
                    {(run.relation === 'slice' || run.is_scout) && (
                        <div className="flex flex-wrap gap-1">
                            {run.relation === 'slice' && <LemonTag size="small">With a filter</LemonTag>}
                            {run.is_scout && <LemonTag size="small">Scout</LemonTag>}
                        </div>
                    )}
                </div>
            ),
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
                    Part of the last scan failed, so the{' '}
                    {Array.from(failedSections)
                        .map((section) => SECTION_LABELS[section] ?? section)
                        .join(' and ')}{' '}
                    are missing. Run a new scan from the <Link to={urls.dataCatalog('usage')}>catalog's usage tab</Link>{' '}
                    to try again.
                </LemonBanner>
            )}
            <div className="flex flex-wrap gap-x-8 gap-y-2">
                <div className="flex flex-col">
                    <span className="text-secondary text-xs">Agent runs</span>
                    <div className="flex flex-wrap items-center gap-1">
                        <span className="text-lg font-semibold">
                            {runsFailed ? UNAVAILABLE : humanFriendlyNumber(directRuns.total)}
                        </span>
                        {directRuns.surfaces.map(([surface, runs]) => (
                            <LemonTag key={surface} size="small">
                                {agentSurfaceLabel(surface)} {humanFriendlyNumber(runs)}
                            </LemonTag>
                        ))}
                    </div>
                    {!runsFailed && (
                        <span className="text-secondary text-xs">
                            By {pluralize(usage.runs?.direct_people ?? 0, 'person', 'people')}
                        </span>
                    )}
                </div>
                <div className="flex flex-col">
                    <span className="text-secondary text-xs">Agent re-derivations</span>
                    <span className="text-lg font-semibold">
                        {rederivationsFailed
                            ? UNAVAILABLE
                            : humanFriendlyNumber(usage.adjusted_runs.length - scoutRederivations)}
                    </span>
                </div>
                <div className="flex flex-col">
                    <span className="text-secondary text-xs">Scouts</span>
                    <span className="text-lg font-semibold">
                        {runsFailed && rederivationsFailed
                            ? UNAVAILABLE
                            : `${runsFailed ? UNAVAILABLE : pluralize(usage.runs?.scout_runs ?? 0, 'run')}, ${
                                  rederivationsFailed ? UNAVAILABLE : pluralize(scoutRederivations, 're-derivation')
                              }`}
                    </span>
                </div>
            </div>
            {!rederivationsFailed && (
                <LemonTable
                    id="metric-usage-runs"
                    columns={columns}
                    dataSource={usage.adjusted_runs}
                    pagination={{ pageSize: 20, hideOnSinglePage: true }}
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
            )}
        </div>
    )
}
