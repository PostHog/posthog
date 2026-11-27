import { dayjs } from 'lib/dayjs'

/** What the first seen read covered, since occurrences before `checkedFrom`, a date in the project's calendar, were
 * never read. */
export function firstSeenTooltip(checkedFrom: string): string {
    return `Earliest activity since ${dayjs(checkedFrom).format('MMM D, YYYY')}. Nothing older was checked.`
}
