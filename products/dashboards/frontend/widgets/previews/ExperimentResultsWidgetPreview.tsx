import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'
import { NotebookCompactTable } from 'scenes/experiments/notebook/NotebookCompactTable'

import type { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import type { ExperimentStatus } from '~/types'

import { experimentResultsSamplePayload } from '../../components/WidgetCard/widgetOverviewStoryFixtures'

const PREVIEW_EXPERIMENT = experimentResultsSamplePayload.experiment
const PREVIEW_METRIC = experimentResultsSamplePayload.metrics[0]

export function ExperimentResultsWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none flex flex-col gap-2 p-2 shadow-sm">
            <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">{PREVIEW_EXPERIMENT.name}</span>
                <StatusTag status={PREVIEW_EXPERIMENT.status as ExperimentStatus} />
            </div>
            <NotebookCompactTable
                result={PREVIEW_METRIC.result as unknown as NewExperimentQueryResponse}
                metric={PREVIEW_METRIC.metric as unknown as ExperimentMetric}
            />
        </div>
    )
}
