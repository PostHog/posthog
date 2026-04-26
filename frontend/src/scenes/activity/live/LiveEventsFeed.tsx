import './LiveEventsTable.scss'

import clsx from 'clsx'
import { type ReactNode, useMemo } from 'react'

import { IconPauseFilled } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { EventCopyLinkButton } from '~/queries/nodes/DataTable/EventRowActions'
import { LiveEvent } from '~/types'

export type LiveEventsFeedColumn = 'event' | 'person' | 'url' | 'timestamp' | 'more'

const ALL_COLUMNS: LiveEventsFeedColumn[] = ['event', 'person', 'url', 'timestamp', 'more']

const COLUMN_DEFINITIONS: Record<LiveEventsFeedColumn, LemonTableColumn<LiveEvent, keyof LiveEvent | undefined>> = {
    event: {
        title: 'Event',
        key: 'event',
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} />
        },
    },
    person: {
        title: 'Person distinct ID',
        tooltip:
            'Some events may be missing a person profile – this is expected, because live events are streamed before person processing completes',
        key: 'person' as any,
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <PersonDisplay person={{ distinct_id: event.distinct_id }} />
        },
    },
    url: {
        title: 'URL / Screen',
        key: '$current_url' as any,
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return (
                <span>
                    {event.properties['$current_url'] ||
                        event.properties['$screen_name'] ||
                        event.properties['$pathname']}
                </span>
            )
        },
    },
    timestamp: {
        title: 'Time',
        key: 'timestamp',
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <TZLabel time={event.timestamp} />
        },
    },
    more: {
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
}

export interface LiveEventsFeedProps {
    events: LiveEvent[]
    columns?: LiveEventsFeedColumn[]
    emptyState?: ReactNode
    streamPaused?: boolean
    className?: string
}

export function LiveEventsFeed({
    events,
    columns = ALL_COLUMNS,
    emptyState,
    streamPaused = false,
    className,
}: LiveEventsFeedProps): JSX.Element {
    const tableColumns = useMemo(() => columns.map((col) => COLUMN_DEFINITIONS[col]), [columns])

    const defaultEmptyState = (
        <div className="flex flex-col justify-center items-center gap-4 p-6">
            {!streamPaused ? <Spinner className="text-4xl" textColored /> : <IconPauseFilled className="text-4xl" />}
            <span className="text-lg font-title font-semibold leading-tight">
                {!streamPaused ? 'Waiting for events…' : 'Stream paused'}
            </span>
        </div>
    )

    return (
        <LemonTable
            className={clsx('LiveEventsTable__table', className)}
            columns={tableColumns}
            data-attr="live-events-table"
            rowKey="uuid"
            dataSource={events}
            useURLForSorting={false}
            emptyState={emptyState ?? defaultEmptyState}
            nouns={['event', 'events']}
        />
    )
}
