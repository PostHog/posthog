import { dayjs } from 'lib/dayjs'

export interface FirstSeenLabel {
    text: string
    tooltip: string
}

const DATE_FORMAT = 'MMM D, YYYY'

function formatDate(date: string): string {
    return dayjs(date).format(DATE_FORMAT)
}

/** The first seen date of an error, with what the lookback covered, since occurrences before it were never read. */
export function firstSeenLabel(firstSeen: string | null, checkedFrom: string): FirstSeenLabel {
    return {
        text: firstSeen === null ? '-' : formatDate(firstSeen),
        tooltip: `Earliest activity since ${formatDate(checkedFrom)}. Nothing older was checked.`,
    }
}
