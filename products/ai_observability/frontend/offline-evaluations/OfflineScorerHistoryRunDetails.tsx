import type { OfflineHistoryPointApi } from '../generated/api.schemas'
import { OfflineExperimentStatus } from './OfflineExperimentStatus'
import { offlineRunSourceLabel } from './offlineOverviewState'
import { formatOfflineScore } from './offlineScoreTrends'

export function OfflineScorerHistoryRunDetails({
    point: { experiment, summary },
}: {
    point: OfflineHistoryPointApi
}): JSX.Element {
    return (
        <div className="space-y-3 p-2">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">Run details</span>
                <OfflineExperimentStatus status={experiment.status} />
                <span className="text-muted">
                    {experiment.run_source ? offlineRunSourceLabel(experiment.run_source) : 'Source not specified'}
                </span>
            </div>
            <div className="text-xs space-y-1">
                <div className="break-words">{`Score: ${formatOfflineScore(summary)}`}</div>
                <div>{`${summary.status_counts.ok} successful / ${summary.observed_item_count} observed items`}</div>
                <div>{`${summary.status_counts.error} errors · ${summary.status_counts.skipped} skipped · ${summary.status_counts.not_applicable} not applicable · ${summary.missing_result_count} missing`}</div>
                <div>{`${summary.distinct_case_count} distinct cases · ${summary.items_with_case_key_count} with case keys · ${summary.items_without_case_key_count} without case keys`}</div>
                <div>{`${summary.trial_item_count} trial items · ${summary.distinct_trial_count} case/trial identities`}</div>
            </div>
            <dl className="text-xs grid gap-x-4 gap-y-2 @min-[48rem]/main-content:grid-cols-2">
                {[
                    ['Suite', experiment.suite_key],
                    ['Application', experiment.application_version],
                    ['Model', experiment.model_version],
                    ['Prompt', experiment.prompt_version],
                    ['Dataset source', experiment.dataset_source],
                    ['Dataset', experiment.dataset_identifier],
                    ['Dataset revision', experiment.dataset_revision_identifier],
                ]
                    .filter(([, value]) => value !== null)
                    .map(([label, value]) => (
                        <div key={label} className="min-w-0">
                            <dt className="text-muted">{label}</dt>
                            <dd className="m-0 break-words">{value}</dd>
                        </div>
                    ))}
            </dl>
        </div>
    )
}
