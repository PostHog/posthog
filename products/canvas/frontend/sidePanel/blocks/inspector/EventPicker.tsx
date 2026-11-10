import { useActions, useValues } from 'kea'

import { canvasBlockPickersLogic } from './canvasBlockPickersLogic'
import { eventLabel } from './pickerLabels'
import { SearchPicker } from './SearchPicker'

/** Picks one event, from the project's most common ones or typed in. */
export function EventPicker({ value, onChange }: { value: string; onChange: (value: string) => void }): JSX.Element {
    const { topEvents, topEventsLoading, topEventsError } = useValues(canvasBlockPickersLogic)
    const { ensureTopEvents } = useActions(canvasBlockPickersLogic)
    return (
        <SearchPicker
            value={value}
            onChange={(next) => {
                if (next) {
                    onChange(next)
                }
            }}
            options={topEvents ?? []}
            loading={topEventsLoading}
            error={topEventsError ? 'Options did not load. Close and reopen this list to try again.' : null}
            onOpen={ensureTopEvents}
            placeholder="Pick an event"
            searchPlaceholder="Search events…"
            ariaLabel="Event"
            format={eventLabel}
        />
    )
}
