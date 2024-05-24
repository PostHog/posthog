import { IconPauseFilled, IconPlayFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { liveEventsTableLogic } from 'scenes/events-management/live-events/liveEventsTableLogic'

import { LiveEvent } from '~/types'

const columns: LemonTableColumns<LiveEvent> = [
    {
        title: 'ID',
        key: 'uuid',
        render: function Render(_, event: LiveEvent) {
            return <span>{event.uuid}</span>
        },
    },
    {
        title: 'Event',
        key: 'event',
        render: function Render(_, event: LiveEvent) {
            return <span>{event.event}</span>
        },
    },
    {
        title: 'Timestamp',
        key: 'timestamp',
        render: function Render(_, event: LiveEvent) {
            return <TZLabel time={event.timestamp} />
        },
    },
]

export function LiveEventsTable(): JSX.Element {
    const { events, stats, streamPaused } = useValues(liveEventsTableLogic)
    const { pauseStream, resumeStream } = useActions(liveEventsTableLogic)
    const { openSupportForm } = useActions(supportLogic)

    return (
        <div data-attr="manage-events-table">
            <LemonBanner className="mb-4" type="info">
                Live events is a beta feature and may not be fully accurate.{' '}
                <Link onClick={() => openSupportForm({ kind: 'feedback' })}>Contact us</Link> if you need help with this
                feature.
            </LemonBanner>
            <div className="mb-2 flex w-full justify-between items-center">
                <div className="flex justify-center">
                    <Tooltip title="This number represents the current number of unique users on events being send to PostHog.">
                        <div className="flex flex-justify-center items-center bg-white px-3 py-2 rounded border border-3000 text-xs font-medium text-gray-600 space-x-2.5">
                            <span className="relative flex h-2.5 w-2.5">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger opacity-50" />
                                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-danger" />
                            </span>
                            <p className="mb-0 text-sm">
                                Live users on product:{' '}
                                <b>{stats?.users_on_product ? `${stats?.users_on_product}` : '-'}</b>
                            </p>
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
                        type="primary"
                        onClick={streamPaused ? resumeStream : pauseStream}
                    >
                        {streamPaused ? 'Play' : 'Pause'}
                    </LemonButton>
                </div>
            </div>
            <LemonTable
                // @ts-expect-error - TODO: Fix LemonTable types
                columns={columns}
                data-attr="live-events-table"
                rowKey="uuid"
                dataSource={events}
                useURLForSorting={false}
                emptyState="No live events"
                nouns={['event', 'events']}
            />
        </div>
    )
}
