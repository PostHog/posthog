import { dayjs } from 'lib/dayjs'
import { eventToDescription } from 'lib/utils'

import { EventType } from '~/types'

import { EventIcon } from './EventIcon'

type SessionEventProps = { event: EventType }

export const SessionEvent = ({ event }: SessionEventProps): JSX.Element => (
    <div className="bg-surface-primary relative flex items-center justify-between rounded border py-1 pl-3 pr-4 text-xs">
        <div className="flex items-center">
            <EventIcon event={event} />
            <b className="ml-3">{eventToDescription(event)}</b>
        </div>
        <div className="text-secondary flex items-center font-bold">
            <span>{dayjs(event.timestamp).format('h:mm:ss A')}</span>
        </div>
    </div>
)
