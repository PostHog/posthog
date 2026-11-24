import type { ExperimentScorePreviewApi } from '../generated/api.schemas'

const statusLabels: Record<string, string> = {
    mixed_versions: 'Mixed versions',
    missing_input: 'Missing scorer results',
    no_successful_items: 'No successful items',
    unavailable_statistic: 'Statistic unavailable for this version',
    overlapping_items: 'Multiple versions scored the same item',
    formula_error: 'Formula output is outside its configuration',
    pending: 'Waiting for completion',
    failed: 'Experiment failed',
}

export function experimentScoreLabel(score: ExperimentScorePreviewApi): string {
    if (score.status !== 'ok' || score.value === null) {
        return statusLabels[score.status] ?? 'Unavailable'
    }
    return Array.isArray(score.value)
        ? score.value.join(', ')
        : typeof score.value === 'number'
          ? score.value.toLocaleString(undefined, { maximumSignificantDigits: 6 })
          : String(score.value)
}

export function ExperimentScoreResult({ score }: { score: ExperimentScorePreviewApi }): JSX.Element {
    return (
        <div className="space-y-1">
            <strong>{experimentScoreLabel(score)}</strong>
            {score.inputs.map((input) => (
                <div key={input.alias} className="text-sm text-muted">
                    <code>{input.alias}</code> · {input.statistic.replaceAll('_', ' ')}
                    {input.status !== 'ok' && <> · {statusLabels[input.status]}</>}
                    {input.sources.map((source) => (
                        <span key={source.version_id}>
                            {' · '}v{source.version}{' '}
                            {source.value === null
                                ? '—'
                                : input.statistic.endsWith('_rate')
                                  ? source.value.toLocaleString(undefined, {
                                        style: 'percent',
                                        maximumFractionDigits: 2,
                                    })
                                  : source.value.toLocaleString(undefined, { maximumSignificantDigits: 6 })}{' '}
                            ({source.successful_items} successful)
                        </span>
                    ))}
                </div>
            ))}
        </div>
    )
}
