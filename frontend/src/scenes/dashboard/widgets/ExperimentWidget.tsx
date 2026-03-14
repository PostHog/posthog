
import { useEffect, useState } from 'react'

import { IconFlask } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

interface ExperimentWidgetProps {
    tileId: number
    config: Record<string, any>
}

interface ExperimentSummary {
    id: number
    name: string
    description: string
    start_date: string | null
    end_date: string | null
    feature_flag_key: string
    parameters: Record<string, any>
    filters: Record<string, any>
}

const STATUS_COLORS: Record<string, string> = {
    complete: 'bg-success-highlight text-success',
    running: 'bg-warning-highlight text-warning',
    draft: 'bg-surface-secondary text-muted',
}

function getExperimentStatus(experiment: ExperimentSummary): { label: string; colorClass: string } {
    if (experiment.end_date) {
        return { label: 'Complete', colorClass: STATUS_COLORS.complete }
    }
    if (experiment.start_date) {
        return { label: 'Running', colorClass: STATUS_COLORS.running }
    }
    return { label: 'Draft', colorClass: STATUS_COLORS.draft }
}

function ExperimentWidget({ config }: ExperimentWidgetProps): JSX.Element {
    const [experiment, setExperiment] = useState<ExperimentSummary | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const experimentId = config.experiment_id

    useEffect(() => {
        if (!experimentId) {
            setError('No experiment configured')
            setLoading(false)
            return
        }

        setLoading(true)
        api.get(`api/projects/@current/experiments/${experimentId}`)
            .then((data) => {
                setExperiment(data as ExperimentSummary)
                setLoading(false)
            })
            .catch(() => {
                setError('Failed to load experiment')
                setLoading(false)
            })
    }, [experimentId])

    if (loading) {
        return (
            <div className="p-4 space-y-3">
                <LemonSkeleton className="h-6 w-1/2" />
                <LemonSkeleton className="h-4 w-3/4" />
                <LemonSkeleton className="h-24 w-full" />
            </div>
        )
    }

    if (error || !experiment) {
        return (
            <div className="p-4 flex flex-col items-center justify-center h-full text-muted">
                <IconFlask className="text-3xl mb-2" />
                <span>{error || 'Experiment not found'}</span>
            </div>
        )
    }

    const status = getExperimentStatus(experiment)
    const variants = experiment.parameters?.feature_flag_variants ?? []

    return (
        <div className="p-4 space-y-3 h-full overflow-auto">
            <div className="flex items-center gap-2">
                <h4 className="font-semibold text-base mb-0 flex-1 truncate">{experiment.name}</h4>
                <span className={`text-xs font-medium px-2 py-0.5 rounded ${status.colorClass}`}>
                    {status.label}
                </span>
            </div>

            {experiment.description && (
                <p className="text-sm text-muted mb-0 line-clamp-2">{experiment.description}</p>
            )}

            {experiment.feature_flag_key && (
                <div className="text-xs text-muted">
                    <span className="font-medium">Feature flag:</span> {experiment.feature_flag_key}
                </div>
            )}

            {variants.length > 0 && (
                <div className="space-y-1">
                    <div className="text-xs font-medium text-muted uppercase">Variants</div>
                    <div className="flex flex-wrap gap-1">
                        {variants.map((variant: { key: string; rollout_percentage?: number }) => (
                            <span
                                key={variant.key}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-secondary text-xs"
                            >
                                {variant.key}
                                {variant.rollout_percentage != null && (
                                    <span className="text-muted">({variant.rollout_percentage}%)</span>
                                )}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            <div className="pt-2">
                <LemonButton type="secondary" size="small" to={urls.experiment(experimentId)} fullWidth center>
                    View full experiment
                </LemonButton>
            </div>
        </div>
    )
}

export default ExperimentWidget
