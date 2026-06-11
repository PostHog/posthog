import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'

import type { ExperimentStatus } from '~/types'

import { experimentsSampleListRows } from '../../components/WidgetCard/widgetOverviewStoryFixtures'

export function ExperimentsListWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none flex flex-col shadow-sm">
            {experimentsSampleListRows.map((experiment) => (
                <div key={experiment.id} className="flex items-center justify-between gap-2 border-b px-2 py-2">
                    <span className="truncate font-semibold">{experiment.name}</span>
                    <StatusTag status={experiment.status as ExperimentStatus} />
                </div>
            ))}
        </div>
    )
}
