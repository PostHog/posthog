import { useValues } from 'kea'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { liveEventsLogic } from 'scenes/activity/live/liveEventsLogic'

/**
 * Latest live event, shown beside the install step's verification state.
 *
 * The width is fixed and the event name truncates: this chip shares a flex row with the step
 * title, so a content-sized chip re-wrapped the title between one and two lines every time an
 * event with a longer name arrived.
 *
 * `data-attr` keeps the `table` suffix from the LemonTable this replaced, because data-attr values
 * are wire strings that dashboards and tests can depend on.
 */
export function OnboardingLiveEvents(): JSX.Element | null {
    const { events } = useValues(liveEventsLogic)
    const latestEvent = events[0]

    if (!latestEvent) {
        return null
    }

    return (
        <div
            className="flex items-center gap-2 w-72 max-w-full min-w-0 px-2 py-1 border rounded bg-surface-primary"
            data-attr="onboarding-live-events-table"
            title={latestEvent.event}
        >
            <span className="relative flex h-2.5 w-2.5 shrink-0">
                <span
                    className="absolute inline-flex h-full w-full rounded-full bg-success animate-ping"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ opacity: 0.75 }}
                />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-success" />
            </span>
            <PropertyKeyInfo
                value={latestEvent.event}
                type={TaxonomicFilterGroupType.Events}
                className="text-sm min-w-0"
            />
            <TZLabel time={latestEvent.timestamp} className="ml-auto shrink-0 text-xs text-muted" />
        </div>
    )
}
