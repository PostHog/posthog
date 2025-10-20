import { useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumn, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { HeatmapScreenshotType } from '~/types'

import { heatmapsSceneLogic } from './heatmapsSceneLogic'

export const scene: SceneExport = {
    component: HeatmapsScene,
    logic: heatmapsSceneLogic,
    settingSectionId: 'environment-autocapture',
}

export function HeatmapsScene(): JSX.Element {
    const { savedHeatmaps, savedHeatmapsLoading } = useValues(heatmapsSceneLogic())

    const columns: LemonTableColumns<HeatmapScreenshotType> = [
        {
            title: 'URL',
            dataIndex: 'url',
            render: (_, row) => (
                <Link to={urls.heatmap(row.id.toString())}>
                    <span className="truncate max-w-[32rem] inline-block align-middle">{row.url}</span>
                </Link>
            ),
        },
        {
            title: 'Width',
            dataIndex: 'width',
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (_, row) => new Date(row.created_at).toLocaleString(),
        },
        {
            ...(createdByColumn<HeatmapScreenshotType>() as LemonTableColumn<
                HeatmapScreenshotType,
                keyof HeatmapScreenshotType | undefined
            >),
            width: 0,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Heatmaps].name}
                description={sceneConfigurations[Scene.Heatmaps].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Heatmaps].iconType || 'default',
                }}
                actions={
                    <LemonButton
                        type="primary"
                        to={urls.heatmap('new')}
                        data-attr="heatmaps-new-heatmap-button"
                        size="small"
                        icon={<IconPlusSmall />}
                    >
                        New heatmap
                    </LemonButton>
                }
            />
            <SceneDivider />
            <LemonBanner
                type="info"
                dismissKey="heatmaps-beta-banner"
                className="mb-4"
                action={{ children: 'Send feedback', id: 'heatmaps-feedback-button' }}
            >
                <p>
                    Heatmaps is in beta. Please let us know what you'd like to see here and/or report any issues
                    directly to us!
                </p>
            </LemonBanner>

            <div className="mb-4">
                <LemonTable dataSource={savedHeatmaps} loading={savedHeatmapsLoading} columns={columns} rowKey="id" />
            </div>
        </SceneContent>
    )
}
