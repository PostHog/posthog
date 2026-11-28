import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSearchableSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { comparisonUrl, MAX_COMPARISON_RUNS } from './offlineComparison'
import { offlineComparisonLogic, type OfflineComparisonProps } from './offlineComparisonLogic'
import { OfflineComparisonTable } from './OfflineComparisonTable'

export function OfflineExperimentComparison({
    canOpenDatasets,
    ...props
}: OfflineComparisonProps & { canOpenDatasets: boolean }): JSX.Element {
    const { experimentIds } = props
    const { results, resultsLoading } = useValues(offlineComparisonLogic(props))
    const { loadComparison } = useActions(offlineComparisonLogic(props))
    const { searchParams } = useValues(router)
    const baselineId = experimentIds[0]
    const entries = experimentIds.flatMap((id) => (results?.[id] ? [{ id, result: results[id] }] : []))
    const orderedRuns = entries.flatMap(({ result }) => ('experiment' in result ? [result] : []))
    const failures = entries.flatMap(({ id, result }) => ('error' in result ? [{ id, ...result }] : []))
    return (
        <section aria-label="Experiment comparison" className="min-w-0 space-y-3">
            <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={comparisonUrl([], searchParams)}>
                Back to experiments
            </LemonButton>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="mb-0">Compare experiments</h2>
                {entries.length > 1 && orderedRuns.length > 0 && (
                    <LemonSearchableSelect
                        size="small"
                        searchPlaceholder="Search experiments"
                        searchInputDataAttr="offline-comparison-search-baselines"
                        aria-label="Baseline experiment"
                        data-attr="offline-comparison-baseline"
                        value={baselineId}
                        options={entries.map(({ id, result }) =>
                            'error' in result
                                ? {
                                      value: id,
                                      label: result.name,
                                      disabledReason: 'Could not load this experiment',
                                  }
                                : {
                                      value: id,
                                      label: result.experiment.name,
                                      labelInMenu: (
                                          <>
                                              {result.experiment.name} · <TZLabel time={result.experiment.started_at} />
                                          </>
                                      ),
                                  }
                        )}
                        onChange={(id) =>
                            router.actions.push(
                                comparisonUrl([id, ...experimentIds.filter((other) => other !== id)], searchParams)
                            )
                        }
                        renderButtonContent={(option) => (
                            <span className="block max-w-52 truncate">Baseline · {option?.label}</span>
                        )}
                    />
                )}
            </div>
            {!experimentIds.length ? (
                <LemonBanner type="warning">
                    Select between 2 and {MAX_COMPARISON_RUNS} experiments from the list to compare them.
                </LemonBanner>
            ) : !results ? (
                <LemonSkeleton className="h-48" />
            ) : (
                <>
                    {failures.length > 0 && (
                        <LemonBanner
                            type="warning"
                            action={{
                                children: 'Retry failed runs',
                                loading: resultsLoading,
                                onClick: () => loadComparison(),
                            }}
                        >
                            <strong>
                                {orderedRuns.length
                                    ? 'Some experiments could not be loaded.'
                                    : 'Could not load the selected experiments.'}
                            </strong>
                            <ul className="my-1">
                                {failures.map(({ id, name, error }) => (
                                    <li key={id}>
                                        {name} · {error}
                                    </li>
                                ))}
                            </ul>
                            {orderedRuns.length > 0 && failures.some(({ id }) => id === baselineId) && (
                                <span>
                                    The baseline is unavailable. Retry or choose another baseline to see score changes.
                                </span>
                            )}
                        </LemonBanner>
                    )}
                    {orderedRuns.length > 0 && (
                        <OfflineComparisonTable
                            orderedRuns={orderedRuns}
                            experimentIds={experimentIds}
                            canOpenDatasets={canOpenDatasets}
                        />
                    )}
                </>
            )}
        </section>
    )
}
