import { IconArrowLeft, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
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
        render: (_, savedMetric) => {
            return <div className="font-semibold">{savedMetric.name}</div>
        },
    },
    {
        key: 'description',
        title: 'Description',
        dataIndex: 'description',
    },
    createdByColumn<SavedMetric>() as LemonTableColumn<SavedMetric, keyof SavedMetric | undefined>,
    createdAtColumn<SavedMetric>() as LemonTableColumn<SavedMetric, keyof SavedMetric | undefined>,
    {
        key: 'actions',
        title: 'Actions',
        render: (_, savedMetric) => {
            return (
                <LemonButton
                    className="max-w-72"
                    type="secondary"
                    size="xsmall"
                    icon={<IconPencil />}
                    onClick={() => {
                        router.actions.push(urls.experimentsSavedMetric(savedMetric.id))
                    }}
                />
            )
        },
    },
]

export function SavedMetrics(): JSX.Element {
    const { savedMetrics, savedMetricsLoading } = useValues(savedMetricsLogic)

    return (
        <div className="space-y-4">
            <LemonButton
                type="tertiary"
                className="inline-flex"
                to={urls.experiments()}
                icon={<IconArrowLeft />}
                size="small"
            >
                Back to experiments
            </LemonButton>
            <LemonBanner type="info">
                Shared metrics let you create reusable metrics that you can quickly add to any experiment. They are
                ideal for tracking key metrics like conversion rates or revenue across different experiments without
                having to set them up each time.
            </LemonBanner>
            <div className="flex justify-end">
                <LemonButton size="small" type="primary" to={urls.experimentsSavedMetric('new')}>
                    New shared metric
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={savedMetrics || []}
                loading={savedMetricsLoading}
                emptyState={<div>You haven't created any shared metrics yet.</div>}
            />
        </div>
    )
}
