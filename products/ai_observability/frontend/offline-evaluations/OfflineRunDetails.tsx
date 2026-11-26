import { Fragment } from 'react'

import { TZLabel } from 'lib/components/TZLabel'

import type { OfflineExperimentReadApi } from '../generated/api.schemas'

const metadataFields = [
    ['suite_key', 'Suite key'],
    ['dataset_source', 'Dataset source'],
    ['dataset_identifier', 'Dataset ID'],
    ['dataset_revision_identifier', 'Dataset revision'],
    ['application_version', 'Application version'],
    ['model_version', 'Model version'],
    ['prompt_version', 'Prompt version'],
] as const

export function OfflineRunDetails({ experiment }: { experiment: OfflineExperimentReadApi }): JSX.Element {
    return (
        <details className="rounded-lg border bg-surface-primary px-4 py-3">
            <summary className="cursor-pointer font-medium" data-attr="offline-experiment-run-details">
                Run details
            </summary>
            <dl className="mt-3 mb-0 grid grid-cols-[fit-content(40%)_minmax(0,1fr)] items-baseline gap-x-6 gap-y-2 border-t pt-3 text-sm [&_dt]:text-muted [&_dd]:m-0 [&_dd]:break-words [&_dd]:font-medium">
                <dt>Items received</dt>
                <dd className="tabular-nums">
                    {experiment.accepted_item_count}
                    {experiment.expected_item_count !== null && (
                        <span className="font-normal text-muted">{` / ${experiment.expected_item_count} expected`}</span>
                    )}
                </dd>
                <dt>Visible results</dt>
                <dd>{experiment.visible_result_count ?? 'Unavailable'}</dd>
                {experiment.expected_result_count !== null && (
                    <>
                        <dt>Expected results across all scorers</dt>
                        <dd>{experiment.expected_result_count}</dd>
                    </>
                )}
                <dt>Experiment ID</dt>
                <dd className="font-mono" translate="no">
                    {experiment.id}
                </dd>
                {metadataFields.map(
                    ([field, label]) =>
                        experiment[field] != null && (
                            <Fragment key={field}>
                                <dt>{label}</dt>
                                <dd translate="no">{experiment[field]}</dd>
                            </Fragment>
                        )
                )}
                <dt>Received</dt>
                <dd>
                    <TZLabel time={experiment.created_at} />
                </dd>
                {experiment.finished_at && (
                    <>
                        <dt>Closed</dt>
                        <dd>
                            <TZLabel time={experiment.finished_at} />
                        </dd>
                    </>
                )}
                {experiment.updated_at && (
                    <>
                        <dt>Last edited</dt>
                        <dd>
                            <TZLabel time={experiment.updated_at} />
                        </dd>
                    </>
                )}
            </dl>
        </details>
    )
}
