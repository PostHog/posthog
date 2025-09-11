import clsx from 'clsx'
import { useValues } from 'kea'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TZLabel } from 'lib/components/TZLabel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { liveEventsTableLogic } from 'scenes/activity/live/liveEventsTableLogic'

import type { LiveEvent } from '~/types'

const columns: LemonTableColumns<LiveEvent> = [
    {
        title: 'Event',
        key: 'event',
        className: 'max-w-52',
        render: function Render(_, event: LiveEvent) {
            return (
                <span className="flex items-center gap-x-2">
                    <span className="relative flex h-2.5 w-2.5">
                        <span
                            className={clsx('absolute inline-flex h-full w-full rounded-full bg-success animate-ping')}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ opacity: 0.75 }}
                        />
                        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-success" />
                    </span>
                    <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} />
                </span>
            )
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

export function OnboardingLiveEvents(): JSX.Element | null {
    const { events } = useValues(liveEventsTableLogic({ tabId: 'onboarding' }))

    if (events.length === 0) {
        return null
    }

    return (
        <LemonTable
            columns={columns}
            data-attr="onboarding-live-events-table"
            rowKey="uuid"
            showHeader={false}
            dataSource={events.slice(0, 1)}
            useURLForSorting={false}
            nouns={['event', 'events']}
        />
    )
}
