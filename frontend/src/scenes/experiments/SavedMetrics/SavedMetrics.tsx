import { IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonTable,
    LemonTableColumns,
    Link,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { useState } from 'react'

import { Holdout, holdoutsLogic, NEW_HOLDOUT } from '../holdoutsLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic } from '../experimentsLogic'
import { urls } from 'scenes/urls'
import { PageHeader } from 'lib/components/PageHeader'
import { SavedMetricLogicProps, savedMetricsLogic } from './savedMetricsLogic'
import { SavedMetric } from './savedMetricLogic'
import { router } from 'kea-router'

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
