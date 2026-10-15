import { LemonCard, LemonCollapse, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ExperimentSavedMetricLinkedExperimentApi } from 'products/experiments/frontend/generated/api.schemas'

export function SharedMetricLinkedExperiments({
    experiments,
}: {
    experiments: readonly ExperimentSavedMetricLinkedExperimentApi[]
}): JSX.Element | null {
    if (experiments.length === 0) {
        return null
    }

    const sortedExperiments = [...experiments].sort((a, b) => Number(b.is_running) - Number(a.is_running))
    const countLabel = experiments.length === 1 ? '1 experiment' : `${experiments.length} experiments`

    const experimentList = (
        <ul className="flex flex-col gap-1.5">
            {sortedExperiments.map((experiment) => (
                <li key={experiment.id} className="flex items-center gap-1.5 min-w-0">
                    <Link to={urls.experiment(experiment.id)} className="truncate text-sm" title={experiment.name}>
                        {experiment.name}
                    </Link>
                    {experiment.is_running && (
                        <LemonTag type="success" size="small" className="shrink-0">
                            Running
                        </LemonTag>
                    )}
                </li>
            ))}
        </ul>
    )

    return (
        <>
            {/* Wide main column: an open card beside the form */}
            <LemonCard hoverEffect={false} className="hidden @min-[64rem]/main-content:block p-4">
                <div className="flex items-baseline justify-between gap-2 mb-3">
                    <h3 className="text-sm font-semibold mb-0">Used in experiments</h3>
                    <span className="text-muted text-xs shrink-0">{countLabel}</span>
                </div>
                <div className="max-h-96 overflow-y-auto">{experimentList}</div>
            </LemonCard>
            {/* Narrow: collapsed by default so a long list does not push the form down */}
            <div className="@min-[64rem]/main-content:hidden">
                <LemonCollapse
                    size="small"
                    panels={[
                        {
                            key: 'linked-experiments',
                            header: `Used in ${countLabel}`,
                            content: <div className="max-h-60 overflow-y-auto">{experimentList}</div>,
                        },
                    ]}
                />
            </div>
        </>
    )
}
