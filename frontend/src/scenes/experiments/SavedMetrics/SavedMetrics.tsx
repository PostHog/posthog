import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SavedMetric } from './savedMetricLogic'
import { savedMetricsLogic } from './savedMetricsLogic'

export const scene: SceneExport = {
    component: SavedMetrics,
    logic: savedMetricsLogic,
}

const columns: LemonTableColumns<SavedMetric> = [
    {
        key: 'name',
        title: 'Name',
        dataIndex: 'name',
    },
    {
        key: 'description',
        title: 'Description',
        dataIndex: 'description',
    },
    {
        key: 'created_at',
        title: 'Created At',
        dataIndex: 'created_at',
    },
    {
        key: 'actions',
        title: 'Actions',
        render: (_, savedMetric) => {
            return (
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => {
                        router.actions.push(urls.experimentsSavedMetric(savedMetric.id))
                    }}
                >
                    Edit
                </LemonButton>
            )
        },
    },
]

export function SavedMetrics(): JSX.Element {
    const { savedMetrics, savedMetricsLoading } = useValues(savedMetricsLogic)

    return (
        <div className="space-y-4">
            <div className="flex justify-end">
                <LemonButton size="small" type="primary" to={urls.experimentsSavedMetric('new')}>
                    New saved metric
                </LemonButton>
            </div>
            <LemonTable columns={columns} dataSource={savedMetrics || []} loading={savedMetricsLoading} />
        </div>
    )
}
