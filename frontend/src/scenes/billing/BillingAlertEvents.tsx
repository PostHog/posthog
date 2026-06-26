import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { BillingAlertEventApi } from '~/generated/core/api.schemas'

export function BillingAlertEvents({
    events,
    failed,
}: {
    events: BillingAlertEventApi[] | undefined
    failed?: boolean
}): JSX.Element {
    if (failed) {
        return <div className="p-2 text-danger">Couldn't load checks.</div>
    }
    if (!events) {
        return <Spinner />
    }
    if (events.length === 0) {
        return <div className="p-2 text-secondary">No checks recorded yet.</div>
    }
    return (
        <div className="deprecated-space-y-2">
            {events.map((event) => (
                <div key={event.id} className="flex flex-col gap-1 border-b pb-2 last:border-b-0">
                    <div className="flex gap-2 items-center">
                        <LemonTag type={event.threshold_breached ? 'danger' : 'success'}>{event.kind}</LemonTag>
                        <span className="text-secondary text-xs">
                            {dayjs(event.created_at).format('YYYY-MM-DD HH:mm')}
                        </span>
                    </div>
                    <span className="text-sm">{event.reason}</span>
                </div>
            ))}
        </div>
    )
}
