import { dayjs } from 'lib/dayjs'
import { eventToDescription } from 'lib/utils'

import { EventType } from '~/types'

import { EventIcon } from './EventIcon'

type SessionEventProps = { event: EventType }

export const SessionEvent = ({ event }: SessionEventProps): JSX.Element => (
    <div className="relative flex items-center justify-between border rounded pl-3 pr-4 py-1 bg-surface-primary text-xs">
        <div className="flex items-center">
            <EventIcon event={event} />
            <b className="ml-3">{eventToDescription(event)}</b>
        </div>
        <div className="flex items-center text-secondary font-bold">
            <span>{dayjs(event.timestamp).format('h:mm:ss A')}</span>
        </div>
    </div>
)
