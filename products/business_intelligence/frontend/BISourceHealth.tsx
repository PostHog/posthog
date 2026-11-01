import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { HEALTH_LABELS, HEALTH_TAG_TYPES } from 'products/data_quality/frontend/checksConstants'
import { DataQualitySubjectHealthApi } from 'products/data_quality/frontend/generated/api.schemas'

export function BISourceHealth({
    health,
    loading,
    error,
    retry,
}: {
    health: DataQualitySubjectHealthApi | null
    loading: boolean
    error: boolean
    retry: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1" aria-label="Data quality check health">
            <span className="font-semibold">Data quality checks</span>
            {loading ? (
                <span>Loading check health…</span>
            ) : error ? (
                <div>
                    Couldn't load check health.{' '}
                    <LemonButton size="xsmall" onClick={retry} loading={loading}>
                        Retry
                    </LemonButton>
                </div>
            ) : health ? (
                health.checks_total === 0 ? (
                    <span>No enabled checks.</span>
                ) : (
                    <div className="flex flex-wrap items-center gap-1">
                        <LemonTag type={HEALTH_TAG_TYPES[health.health] ?? 'muted'}>
                            {HEALTH_LABELS[health.health] ?? 'Unknown'}
                        </LemonTag>
                        <span>
                            {health.checks_total} enabled · {health.checks_failing} failing
                        </span>
                    </div>
                )
            ) : (
                <span>Check health is unavailable for this source.</span>
            )}
            <span className="text-secondary">Latest recorded check results. Certification is a separate review.</span>
        </div>
    )
}
