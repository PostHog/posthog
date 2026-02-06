import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPauseFilled, IconPlayFilled, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTabs, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LiveRecordingsCount, LiveUserCount } from 'lib/components/LiveUserCount'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TZLabel } from 'lib/components/TZLabel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { EventCopyLinkButton } from '~/queries/nodes/DataTable/EventRowActions'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab, LiveEvent } from '~/types'

import { EventName } from 'products/actions/frontend/components/EventName'

import { useActivityTabs } from '../explore/utils'
import { liveEventsLogic } from './liveEventsLogic'
import { liveEventsTableSceneLogic } from './liveEventsTableSceneLogic'

const LIVE_EVENTS_POLL_INTERVAL_MS = 1500

const columns: LemonTableColumns<LiveEvent> = [
    {
        title: 'Event',
        key: 'event',
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} />
        },
    },
    {
        title: 'Person distinct ID',
        tooltip:
            'Some events may be missing a person profile – this is expected, because live events are streamed before person processing completes',
        key: 'person',
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <PersonDisplay person={{ distinct_id: event.distinct_id }} />
        },
    },
    {
        title: 'URL / Screen',
        key: '$current_url',
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <span>{event.properties['$current_url'] || event.properties['$screen_name']}</span>
        },
    },
    {
        title: 'Time',
        key: 'timestamp',
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <TZLabel time={event.timestamp} />
        },
    },
    {
        dataIndex: '__more' as any,
        render: function Render(_, event: LiveEvent) {
            return (
                <More
                    overlay={
                        <Tooltip title="It may take up to a few minutes for the event to show up in the Explore view">
                            <EventCopyLinkButton event={event} />
                        </Tooltip>
                    }
                />
            )
        },
        width: 0,
    },
]

export const scene: SceneExport = {
    component: LiveEventsTable,
    logic: liveEventsTableSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function LiveEventsTable(): JSX.Element {
    const { events, streamPaused, filters } = useValues(liveEventsLogic)
    const { pauseStream, resumeStream, setFilters, clearEvents } = useActions(liveEventsLogic)
    const tabs = useActivityTabs()

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
            <LemonTabs activeKey={ActivityTab.LiveEvents} tabs={tabs} sceneInset className="mb-3" />
            <SceneTitleSection
                name={sceneConfigurations[Scene.Activity].name}
                description={sceneConfigurations[Scene.Activity].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Activity].iconType || 'default_icon_type',
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
            <LemonTable
                columns={columns}
                data-attr="live-events-table"
                rowKey="uuid"
                dataSource={events}
                useURLForSorting={false}
                emptyState={
                    <div className="flex flex-col justify-center items-center gap-4 p-6">
                        {!streamPaused ? (
                            <Spinner className="text-4xl" textColored />
                        ) : (
                            <IconPauseFilled className="text-4xl" />
                        )}
                        <span className="text-lg font-title font-semibold leading-tight">
                            {!streamPaused ? 'Waiting for events…' : 'Stream paused'}
                        </span>
                    </div>
                }
                nouns={['event', 'events']}
            />
        </SceneContent>
    )
}
