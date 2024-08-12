import { IconPauseFilled, IconPlayFilled } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { liveEventsTableLogic } from 'scenes/activity/live/liveEventsTableLogic'

import type { LiveEvent } from '~/types'

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
]

export function LiveEventsTable(): JSX.Element {
    const { events, stats, streamPaused } = useValues(liveEventsTableLogic)
    const { pauseStream, resumeStream } = useActions(liveEventsTableLogic)

    return (
        <div data-attr="manage-events-table">
            <div className="mb-4 flex w-full justify-between items-center">
                <div className="flex justify-center">
                    <Tooltip title="Estimate of users active in the last 30 seconds." placement="right">
                        <div className="flex flex-justify-center items-center bg-bg-light px-3 py-2 rounded border border-3000 text-xs font-medium text-gray-600 space-x-2.5">
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
                <div>
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
        </div>
    )
}
