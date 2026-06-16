import { clsx } from 'clsx'

import { CONCLUSION_DISPLAY_CONFIG } from 'scenes/experiments/constants'
import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'
import { NotebookCompactTable } from 'scenes/experiments/notebook/NotebookCompactTable'

import type { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { type ExperimentConclusion, type ExperimentStatus } from '~/types'

import {
    experimentResultsSamplePayload,
    experimentsSampleListRows,
} from '../../components/WidgetCard/widgetOverviewStoryFixtures'

export function ExperimentsListWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none flex flex-col shadow-sm">
            {experimentsSampleListRows.map((experiment) => {
                const creatorName = experiment.created_by?.first_name || experiment.created_by?.email
                const conclusionConfig = experiment.conclusion
                    ? CONCLUSION_DISPLAY_CONFIG[experiment.conclusion as ExperimentConclusion]
                    : null
                return (
                    <div key={experiment.id} className="flex items-center justify-between gap-2 border-b px-2 py-2">
                        <div className="flex min-w-0 flex-col">
                            <span className="truncate font-semibold text-primary">{experiment.name}</span>
                            {creatorName ? (
                                <span className="truncate text-xs text-muted">Created by {creatorName}</span>
                            ) : null}
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                            {conclusionConfig ? (
                                <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-muted">
                                    <span className={clsx('size-2 shrink-0 rounded-full', conclusionConfig.color)} />
                                    {conclusionConfig.title}
                                </span>
                            ) : null}
                            <StatusTag status={experiment.status as ExperimentStatus} />
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

const RESULTS_PREVIEW_EXPERIMENT = experimentResultsSamplePayload.experiment
const RESULTS_PREVIEW_METRIC = experimentResultsSamplePayload.metrics[0]

export function ExperimentResultsWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none flex flex-col gap-2 p-2 shadow-sm">
            <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">{RESULTS_PREVIEW_EXPERIMENT.name}</span>
                <StatusTag status={RESULTS_PREVIEW_EXPERIMENT.status as ExperimentStatus} />
            </div>
            <NotebookCompactTable
                result={RESULTS_PREVIEW_METRIC.result as unknown as NewExperimentQueryResponse}
                metric={RESULTS_PREVIEW_METRIC.metric as unknown as ExperimentMetric}
            />
        </div>
    )
}
