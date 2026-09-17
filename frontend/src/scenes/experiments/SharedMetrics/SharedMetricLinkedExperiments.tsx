import { LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import type { ExperimentSavedMetricLinkedExperimentApi } from 'products/experiments/frontend/generated/api.schemas'

export function SharedMetricLinkedExperiments({
    experiments,
}: {
    experiments: readonly ExperimentSavedMetricLinkedExperimentApi[]
}): JSX.Element {
    const sortedExperiments = [...experiments].sort((a, b) => Number(b.is_running) - Number(a.is_running))

    return (
        <ScenePanelLabel title="Used in experiments">
            {sortedExperiments.length === 0 ? (
                <span className="text-muted text-sm">Not used in any experiments yet</span>
            ) : (
                <div className="flex flex-col gap-1">
                    {sortedExperiments.map((experiment) => (
                        <div key={experiment.id} className="flex items-center gap-1.5 min-w-0">
                            <Link
                                to={urls.experiment(experiment.id)}
                                className="truncate text-sm"
                                title={experiment.name}
                            >
                                {experiment.name}
                            </Link>
                            {experiment.is_running && (
                                <LemonTag type="success" size="small" className="shrink-0">
                                    Running
                                </LemonTag>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </ScenePanelLabel>
    )
}
