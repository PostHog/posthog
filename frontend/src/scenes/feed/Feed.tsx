import { useActions, useValues } from 'kea'

import {
    IconClock,
    IconComment,
    IconDashboard,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGear,
    IconGraph,
    IconNotification,
    IconRefresh,
    IconRewindPlay,
} from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FeedActivityType } from '~/types'

import { FeedGroupedCard } from './FeedGroupedCard'
import { FeedPreferencesModal } from './FeedPreferencesModal'
import { feedLogic } from './feedLogic'

export const scene: SceneExport = {
    component: Feed,
    logic: feedLogic,
}

function getActivityIcon(type: FeedActivityType): JSX.Element {
    const iconMap: Record<FeedActivityType, JSX.Element> = {
        [FeedActivityType.Dashboard]: <IconDashboard />,
        [FeedActivityType.EventDefinition]: <IconGraph />,
        [FeedActivityType.ExperimentLaunched]: <IconFlask />,
        [FeedActivityType.ExperimentCompleted]: <IconFlask />,
        [FeedActivityType.FeatureFlag]: <IconFlag />,
        [FeedActivityType.Survey]: <IconComment />,
        [FeedActivityType.ReplayPlaylist]: <IconRewindPlay />,
        [FeedActivityType.ExpiringRecordings]: <IconClock />,
        [FeedActivityType.ExternalDataSource]: <IconDatabase />,
    }
    return iconMap[type] || <IconGraph />
}

function getActivityTypeLabel(type: FeedActivityType): string {
    const labels: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: 'Dashboards',
        [FeedActivityType.EventDefinition]: 'Events',
        [FeedActivityType.ExperimentLaunched]: 'Experiments launched',
        [FeedActivityType.ExperimentCompleted]: 'Experiments completed',
        [FeedActivityType.ExternalDataSource]: 'Data sources',
        [FeedActivityType.FeatureFlag]: 'Feature flags',
        [FeedActivityType.Survey]: 'Surveys',
        [FeedActivityType.ReplayPlaylist]: 'Replay playlists',
        [FeedActivityType.ExpiringRecordings]: 'Expiring recordings',
    }
    return labels[type] || type
}

export function Feed(): JSX.Element {
    const { groupedFeedItems, feedLoading, hasMore, filters, preferencesModalOpen } = useValues(feedLogic)
    const { loadFeed, setFilters, resetFilters, openPreferencesModal } = useActions(feedLogic)

    const hasFilters = Boolean(filters.type || filters.date_from || filters.date_to)

    return (
        <>
            <SceneContent>
                <SceneTitleSection
                    name="Feed"
                    description="Stay updated with recent activities and changes in your project"
                    resourceType={{
                        type: 'project',
                        forceIcon: <IconNotification />,
                    }}
                    actions={
                        <div className="flex gap-2 items-center">
                            <LemonSelect
                                placeholder="Filter by type"
                                options={[
                                    { label: 'All types', value: undefined },
                                    ...Object.values(FeedActivityType).map((type) => ({
                                        label: getActivityTypeLabel(type),
                                        value: type,
                                        icon: getActivityIcon(type),
                                    })),
                                ]}
                                value={filters.type}
                                onChange={(value) => setFilters({ ...filters, type: value })}
                            />

                            {hasFilters && (
                                <LemonButton type="secondary" size="small" onClick={resetFilters}>
                                    Clear filters
                                </LemonButton>
                            )}

                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconRefresh />}
                                onClick={() => loadFeed()}
                                loading={feedLoading}
                            >
                                Refresh
                            </LemonButton>

                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconGear />}
                                data-attr="feed-preferences"
                                onClick={openPreferencesModal}
                            >
                                Preferences
                            </LemonButton>
                        </div>
                    }
                />

                <LemonDivider />

                {feedLoading && Object.keys(groupedFeedItems).length === 0 ? (
                    <div className="flex justify-center py-8">
                        <Spinner />
                    </div>
                ) : Object.keys(groupedFeedItems).length === 0 ? (
                    <div className="border rounded p-6 bg-surface-primary text-center">
                        <p className="text-muted">No feed items found. Try adjusting your filters or preferences.</p>
                    </div>
                ) : (
                    <div className="space-y-6">
                        {Object.entries(groupedFeedItems).map(([dateGroup, typeGroups]) => (
                            <div key={dateGroup}>
                                <h3 className="text-muted-alt text-xs uppercase font-semibold mb-2">{dateGroup}</h3>
                                <div className="space-y-4">
                                    {Object.entries(typeGroups).map(([type, items]) => (
                                        <FeedGroupedCard
                                            key={`${dateGroup}-${type}`}
                                            items={items}
                                            type={type as FeedActivityType}
                                        />
                                    ))}
                                </div>
                            </div>
                        ))}

                        {hasMore && (
                            <div className="flex justify-center py-4">
                                <LemonButton type="secondary" onClick={() => loadFeed(true)} loading={feedLoading}>
                                    Load more
                                </LemonButton>
                            </div>
                        )}
                    </div>
                )}
            </SceneContent>

            {preferencesModalOpen && <FeedPreferencesModal />}
        </>
    )
}
