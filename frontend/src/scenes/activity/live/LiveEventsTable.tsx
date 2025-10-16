import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconPauseFilled, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTabs, Spinner, Tooltip } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TZLabel } from 'lib/components/TZLabel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { liveEventsTableLogic } from 'scenes/activity/live/liveEventsTableLogic'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { EventCopyLinkButton } from '~/queries/nodes/DataTable/EventRowActions'
import { ActivityTab, LiveEvent } from '~/types'

import { EventName } from 'products/actions/frontend/components/EventName'

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

export function LiveEventsTable(): JSX.Element {
    const { events, stats, streamPaused, filters } = useValues(liveEventsTableLogic)
    const { pauseStream, resumeStream, setFilters, clearEvents } = useActions(liveEventsTableLogic)

    return (
        <SceneContent data-attr="manage-events-table">
            <LemonTabs
                activeKey={ActivityTab.LiveEvents}
                tabs={[
                    {
                        key: ActivityTab.ExploreEvents,
                        label: 'Explore',
                        link: urls.activity(ActivityTab.ExploreEvents),
                    },
                    {
                        key: ActivityTab.LiveEvents,
                        label: 'Live',
                        link: urls.activity(ActivityTab.LiveEvents),
                    },
                ]}
                sceneInset
            />
            <SceneTitleSection
                name={sceneConfigurations[Scene.LiveEvents].name}
                description={sceneConfigurations[Scene.LiveEvents].description}
                resourceType={{
                    type: sceneConfigurations[Scene.LiveEvents].iconType || 'default_icon_type',
                }}
            />
            <SceneDivider />
            <div className="mb-4 flex w-full justify-between items-center">
                <div className="flex justify-center">
                    <Tooltip title="Estimate of users active in the last 30 seconds." placement="right">
                        <div className="flex justify-center items-center bg-surface-primary px-3 py-2 rounded border border-primary text-xs font-medium text-secondary gap-x-2.5">
                            <span className="relative flex h-2.5 w-2.5">
                                <span
                                    className={clsx(
                                        'absolute inline-flex h-full w-full rounded-full bg-danger',
                                        stats?.users_on_product != null && 'animate-ping'
                                    )}
                                    // Unfortunately we can't use the `opacity-50` class, because we use Tailwind's
                                    // `important: true` and because of that Tailwind's `opacity` completely overrides
                                    // the animation (see https://github.com/tailwindlabs/tailwindcss/issues/9225)
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ opacity: 0.75 }}
                                />
                                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-danger" />
                            </span>
                            <span className="text-sm cursor-default">
                                Users active right now: <b>{stats?.users_on_product ?? '0'}</b>
                            </span>
                        </div>
                    </Tooltip>
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

export const scene: SceneExport = {
    component: LiveEventsTable,
    logic: liveEventsTableLogic,
    settingSectionId: 'environment-autocapture',
}
