import { clsx } from 'clsx'

import { CONCLUSION_DISPLAY_CONFIG } from 'scenes/experiments/constants'
import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'

import type { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { type ExperimentConclusion, type ExperimentStatus } from '~/types'

import {
    experimentResultsSamplePayload,
    experimentsSampleListRows,
} from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { NotebookCompactTable } from '../experiments/LazyNotebookCompactTable'

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

export function ExperimentResultsWidgetPreview(): JSX.Element {
    const experiment = experimentResultsSamplePayload.experiment
    const metric = experimentResultsSamplePayload.metrics[0]
    return (
        <div className="pointer-events-none flex flex-col gap-2 p-2 shadow-sm">
            <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">{experiment.name}</span>
                <StatusTag status={experiment.status as ExperimentStatus} />
            </div>
            <NotebookCompactTable
                result={metric.result as unknown as NewExperimentQueryResponse}
                metric={metric.metric as unknown as ExperimentMetric}
            />
        </div>
    )
}
