import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import {
    IconDashboard,
    IconFlask,
    IconNewspaper,
    IconNotification,
    IconPlaylist,
    IconPulse,
    IconRefresh,
    IconServer,
    IconToggle,
} from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconSurveys } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { availableOnboardingProducts } from 'scenes/onboarding/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { Error404 } from '~/layout/Error404'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { FeedDiscovery } from './FeedDiscovery'
import { FeedGroupedCard } from './FeedGroupedCard'
import { feedLogic } from './feedLogic'

export const scene: SceneExport = {
    component: Feed,
    logic: feedLogic,
}

const FEED_TYPE_CONFIGS: Record<string, { title: string; icon: JSX.Element; color: string; borderColor: string }> = {
    dashboard: {
        title: 'Dashboards',
        icon: <IconDashboard color={availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS].iconColor} />,
        color: availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS].iconColor,
        borderColor: availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS].iconColor,
    },
    event_definition: {
        title: 'Events',
        icon: <IconPulse color={availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS].iconColor} />,
        color: availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS].iconColor,
        borderColor: availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS].iconColor,
    },
    experiment_launched: {
        title: 'Experiments launched',
        icon: <IconFlask color={availableOnboardingProducts[ProductKey.EXPERIMENTS].iconColor} />,
        color: availableOnboardingProducts[ProductKey.EXPERIMENTS].iconColor,
        borderColor: availableOnboardingProducts[ProductKey.EXPERIMENTS].iconColor,
    },
    experiment_completed: {
        title: 'Experiments completed',
        icon: <IconFlask color={availableOnboardingProducts[ProductKey.EXPERIMENTS].iconColor} />,
        color: availableOnboardingProducts[ProductKey.EXPERIMENTS].iconColor,
        borderColor: availableOnboardingProducts[ProductKey.EXPERIMENTS].iconColor,
    },
    feature_flag: {
        title: 'Feature flags',
        icon: <IconToggle color={availableOnboardingProducts[ProductKey.FEATURE_FLAGS].iconColor} />,
        color: availableOnboardingProducts[ProductKey.FEATURE_FLAGS].iconColor,
        borderColor: availableOnboardingProducts[ProductKey.FEATURE_FLAGS].iconColor,
    },
    survey: {
        title: 'Surveys',
        icon: <IconSurveys color={availableOnboardingProducts[ProductKey.SURVEYS].iconColor} />,
        color: availableOnboardingProducts[ProductKey.SURVEYS].iconColor,
        borderColor: availableOnboardingProducts[ProductKey.SURVEYS].iconColor,
    },
    session_recording_playlist: {
        title: 'Replay playlists',
        icon: <IconPlaylist color={availableOnboardingProducts[ProductKey.SESSION_REPLAY].iconColor} />,
        color: availableOnboardingProducts[ProductKey.SESSION_REPLAY].iconColor,
        borderColor: availableOnboardingProducts[ProductKey.SESSION_REPLAY].iconColor,
    },
    external_data_source: {
        title: 'Data sources',
        icon: <IconServer color={availableOnboardingProducts[ProductKey.DATA_WAREHOUSE].iconColor} />,
        color: availableOnboardingProducts[ProductKey.DATA_WAREHOUSE].iconColor,
        borderColor: availableOnboardingProducts[ProductKey.DATA_WAREHOUSE].iconColor,
    },
}

export function Feed(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupedFeedItems, feedItemsLoading, filters, searchQuery, selectedTypes } = useValues(feedLogic)
    const { loadFeed, setFilters, setSearchQuery, setSelectedTypes } = useActions(feedLogic)
    useEffect(() => {
        loadFeed()
    }, [loadFeed])

    // Feature flag gate
    if (!featureFlags[FEATURE_FLAGS.HOME_FEED_TAB]) {
        return <Error404 />
    }

    const hasAnyItems = Object.keys(groupedFeedItems).length > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name="Feed"
                description="Stay updated with recent activities and changes in your project"
                resourceType={{
                    type: 'project',
                    forceIcon: <IconNewspaper />,
                }}
                actions={
                    <div className="flex gap-2 items-center">
                        <LemonSelect
                            placeholder="Filter by date"
                            options={[
                                { label: 'Last 7 days', value: 7 },
                                { label: 'Last 30 days', value: 30 },
                                { label: 'Last 90 days', value: 90 },
                            ]}
                            value={filters.days}
                            onChange={(value) => {
                                if (value) {
                                    setFilters({ days: value })
                                    loadFeed()
                                }
                            }}
                        />

                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            onClick={() => loadFeed()}
                            loading={feedItemsLoading}
                        >
                            Refresh
                        </LemonButton>
                    </div>
                }
            />
            <FeedDiscovery />
            <div className="mb-6">
                <div className="flex items-center justify-between gap-2 mb-3">
                    <div className="flex items-center gap-2">
                        <IconNotification className="text-lg" />
                        <h2 className="text-lg font-semibold mb-0">Updates</h2>
                    </div>
                    <LemonSelect
                        placeholder="All"
                        options={[
                            { label: 'All', value: 'all' },
                            { label: 'Dashboards', value: 'dashboard' },
                            { label: 'Events', value: 'event_definition' },
                            { label: 'Experiments launched', value: 'experiment_launched' },
                            { label: 'Experiments completed', value: 'experiment_completed' },
                            { label: 'Feature flags', value: 'feature_flag' },
                            { label: 'Surveys', value: 'survey' },
                            { label: 'Replay playlists', value: 'session_recording_playlist' },
                            { label: 'Data sources', value: 'external_data_source' },
                        ]}
                        value={selectedTypes}
                        onChange={setSelectedTypes}
                        className="w-60"
                    />
                </div>
                <LemonInput
                    type="search"
                    placeholder="Search updates by name or author..."
                    value={searchQuery}
                    onChange={setSearchQuery}
                    fullWidth
                />
            </div>

            {feedItemsLoading && !hasAnyItems ? (
                <div className="flex justify-center py-8">
                    <Spinner />
                </div>
            ) : !hasAnyItems ? (
                <div className="border rounded p-6 bg-surface-primary text-center">
                    <p className="text-muted">No recent updates found</p>
                    <p className="text-muted-alt text-sm mb-0 mt-1">
                        Try selecting a different time period using the filter above
                    </p>
                </div>
            ) : (
                <div className="space-y-6">
                    {Object.entries(groupedFeedItems).map(([dateGroup, typeGroups]) => (
                        <div key={dateGroup}>
                            <h3 className="text-muted-alt text-xs uppercase font-semibold mb-2">{dateGroup}</h3>
                            <div className="space-y-4">
                                {Object.entries(typeGroups as Record<string, any[]>).map(([type, items]) => {
                                    const config = FEED_TYPE_CONFIGS[type]
                                    if (!config) {
                                        return null
                                    }
                                    return (
                                        <FeedGroupedCard
                                            key={`${dateGroup}-${type}`}
                                            items={items as any[]}
                                            config={config}
                                        />
                                    )
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </SceneContent>
    )
}

export default Feed
