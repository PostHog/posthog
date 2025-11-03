import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTableColumn, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { HeatmapsWarnings } from 'scenes/heatmaps/components/HeatmapsWarnings'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { HeatmapScreenshotType } from '~/types'

import { HEATMAPS_PER_PAGE, heatmapsSceneLogic } from './heatmapsSceneLogic'

export const scene: SceneExport = {
    component: HeatmapsScene,
    logic: heatmapsSceneLogic,
    settingSectionId: 'environment-autocapture',
}

export function HeatmapsScene(): JSX.Element {
    const { savedHeatmaps, savedHeatmapsLoading, filters, totalCount } = useValues(heatmapsSceneLogic)
    const { deleteHeatmap, setHeatmapsFilters } = useActions(heatmapsSceneLogic)

    const columns: LemonTableColumns<HeatmapScreenshotType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, row) => (
                <Link to={urls.heatmap(row.short_id)}>
                    <span className="truncate max-w-[32rem] inline-block align-middle">{row.name}</span>
                </Link>
            ),
        },
        {
            title: 'Page',
            dataIndex: 'url',
            render: (_, row) => (
                <Link to={urls.heatmap(row.short_id)}>
                    <span className="truncate max-w-[32rem] inline-block align-middle">{row.url}</span>
                </Link>
            ),
        },
        {
            title: 'Heatmap data URL',
            dataIndex: 'data_url',
            render: (_, row) => (
                <Link to={urls.heatmap(row.short_id)}>
                    <span className="truncate max-w-[32rem] inline-block align-middle">{row.data_url}</span>
                </Link>
            ),
        },
        {
            title: 'Type',
            dataIndex: 'type',
            render: (_, row) => row.type.charAt(0).toUpperCase() + row.type.slice(1),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: function Render(created_at) {
                return <div>{created_at && typeof created_at === 'string' && <TZLabel time={created_at} />}</div>
            },
        },
        {
            ...(createdByColumn<HeatmapScreenshotType>() as LemonTableColumn<
                HeatmapScreenshotType,
                keyof HeatmapScreenshotType | undefined
            >),
            width: 0,
        },
        {
            width: 0,
            render: function Render(_, row) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="danger"
                                    onClick={() => deleteHeatmap(row.short_id)}
                                    fullWidth
                                    loading={savedHeatmapsLoading}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <HeatmapsWarnings />
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
            <div className="flex justify-between gap-2 items-center flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for heatmaps"
                    onChange={(value) => setHeatmapsFilters({ ...filters, search: value || '' })}
                    value={filters.search || ''}
                />

                <div className="flex items-center gap-2">
                    <span>Created by:</span>
                    <MemberSelect
                        value={filters.createdBy === 'All users' ? null : (filters.createdBy as string | number | null)}
                        onChange={(user) => setHeatmapsFilters({ ...filters, createdBy: user?.id || 'All users' })}
                    />
                </div>
            </div>
            <div className="mb-4">
                <LemonTable
                    dataSource={savedHeatmaps}
                    loading={savedHeatmapsLoading}
                    columns={columns}
                    rowKey="id"
                    pagination={{
                        controlled: true,
                        pageSize: HEATMAPS_PER_PAGE,
                        currentPage: filters.page,
                        entryCount: totalCount,
                        onBackward:
                            (filters.page || 1) > 1
                                ? () => setHeatmapsFilters({ ...filters, page: Math.max(1, (filters.page || 1) - 1) })
                                : undefined,
                        onForward:
                            (filters.page || 1) * HEATMAPS_PER_PAGE < (totalCount || 0)
                                ? () => setHeatmapsFilters({ ...filters, page: (filters.page || 1) + 1 })
                                : undefined,
                    }}
                    nouns={['heatmap', 'heatmaps']}
                />
            </div>
        </SceneContent>
    )
}
