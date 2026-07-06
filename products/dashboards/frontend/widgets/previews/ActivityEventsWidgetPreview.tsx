import { activityEventsSampleEvents } from '../activity/activityEventsSampleData'
import { ActivityEventsWidgetRow } from '../activity/ActivityEventsWidgetRow'

export function ActivityEventsWidgetPreview(): JSX.Element {
    return (
        <div className="flex flex-col divide-y divide-border shadow-sm">
            {activityEventsSampleEvents.map((event) => (
                <ActivityEventsWidgetRow key={event.uuid} event={event} />
            ))}
        </div>
    )
}
