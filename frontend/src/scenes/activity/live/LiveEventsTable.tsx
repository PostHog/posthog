import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPauseFilled, IconPlayFilled, IconRefresh, IconTerminal } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { LiveRecordingsCount, LiveUserCount } from 'lib/components/LiveUserCount'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ActivitySceneTabs } from 'scenes/activity/ActivitySceneTabs'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab, PropertyOperator } from '~/types'

import { EventName } from 'products/actions/frontend/components/EventName'

import { LiveBotPanel } from './LiveBotPanel'
import { LiveEventsFeed } from './LiveEventsFeed'
import { liveEventsLogic } from './liveEventsLogic'
import { liveEventsTableSceneLogic } from './liveEventsTableSceneLogic'

const LIVE_EVENTS_POLL_INTERVAL_MS = 1500

export const scene: SceneExport = {
    component: LiveEventsTable,
    logic: liveEventsTableSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function LiveEventsTable(): JSX.Element {
    const { events, streamPaused, filters } = useValues(liveEventsLogic)
    const { pauseStream, resumeStream, setFilters, clearEvents } = useActions(liveEventsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { isVisible } = usePageVisibility()
    useEffect(() => {
        if (isVisible) {
            resumeStream()
        } else {
            pauseStream()
        }
    }, [isVisible, resumeStream, pauseStream])

    return (
        <SceneContent data-attr="manage-events-table">
            <ActivitySceneTabs activeKey={ActivityTab.LiveEvents} />
            {featureFlags[FEATURE_FLAGS.LIVESTREAM_TUI] && (
                <LemonBanner type="info" className="mb-4" icon={<IconTerminal />} dismissKey="livestream-tui-banner">
                    Stream live events directly in your terminal with <code>posthog-live</code>.{' '}
                    <Link to="https://posthog.com/docs/live-events/cli" target="_blank">
                        Learn more
                    </Link>
                </LemonBanner>
            )}
            <SceneTitleSection
                name={sceneConfigurations[Scene.Activity].name}
                description={sceneConfigurations[Scene.Activity].description}
                resourceType={{
                    type: sceneConfigurations[Scene.LiveEvents].iconType || 'default_icon_type',
                }}
            />
            <div className="mb-4 flex w-full justify-between items-center">
                <div className="flex gap-2">
                    <LiveUserCount pollIntervalMs={LIVE_EVENTS_POLL_INTERVAL_MS} showUpdatedTimeInTooltip={false} />
                    <LiveRecordingsCount pollIntervalMs={LIVE_EVENTS_POLL_INTERVAL_MS} />
                </div>

                <div className="flex gap-2">
                    <LemonButton
                        icon={<IconRefresh className="w-4 h-4" />}
                        type="secondary"
                        onClick={clearEvents}
                        size="small"
                        tooltip="Clear events"
                    />
                    <EventName
                        value={filters.eventType}
                        onChange={(value) => setFilters({ ...filters, eventType: value })}
                        placeholder="Filter by event"
                        allEventsOption="clear"
                    />
                    <PropertyFilters
                        pageKey="live-events"
                        propertyFilters={filters.properties ?? []}
                        onChange={(properties) => setFilters({ ...filters, properties })}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                        operatorAllowlist={[PropertyOperator.Exact]}
                        buttonText="Filter by property"
                    />
                    <LemonButton
                        icon={
                            streamPaused ? (
                                <IconPlayFilled className="w-4 h-4" />
                            ) : (
                                <IconPauseFilled className="w-4 h-4" />
                            )
                        }
                        type="secondary"
                        onClick={streamPaused ? resumeStream : pauseStream}
                        size="small"
                    >
                        {streamPaused ? 'Play' : 'Pause'}
                    </LemonButton>
                </div>
            </div>
            <LiveBotPanel events={events} className="mb-2" />
            <LiveEventsFeed events={events} streamPaused={streamPaused} />
        </SceneContent>
    )
}
