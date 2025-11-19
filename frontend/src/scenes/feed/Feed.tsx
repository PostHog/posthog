import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import {
    IconClock,
    IconDashboard,
    IconFlask,
    IconGear,
    IconNotification,
    IconPlaylist,
    IconPulse,
    IconRefresh,
    IconServer,
    IconToggle,
} from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconSurveys } from 'lib/lemon-ui/icons'
import { availableOnboardingProducts } from 'scenes/onboarding/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/types'

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
    expiring_recordings: {
        title: 'Expiring recordings',
        icon: <IconClock />,
        color: 'rgb(235 157 42)', // Warning orange/amber
        borderColor: 'rgb(235 157 42)',
    },
}

export function Feed(): JSX.Element {
    const { groupedFeedItems, feedItemsLoading, filters } = useValues(feedLogic)
    const { loadFeed, setFilters } = useActions(feedLogic)

    useEffect(() => {
        loadFeed()
    }, [loadFeed])

    const hasAnyItems = Object.keys(groupedFeedItems).length > 0

    return (
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

                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconGear />}
                            data-attr="feed-preferences"
                            disabledReason="Coming soon"
                        >
                            Preferences
                        </LemonButton>
                    </div>
                }
            />

            <LemonDivider />

            <FeedDiscovery />

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
                                {Object.entries(typeGroups).map(([type, items]) => {
                                    const config = FEED_TYPE_CONFIGS[type]
                                    if (!config) {
                                        return null
                                    }
                                    return (
                                        <FeedGroupedCard key={`${dateGroup}-${type}`} items={items} config={config} />
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
