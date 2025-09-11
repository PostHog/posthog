// oxlint-disable-next-line no-restricted-imports
import dayjs, { Dayjs as DayjsOriginal, isDayjs } from 'dayjs'
import duration from 'dayjs/plugin/duration'
import isSameOrAfter from 'dayjs/plugin/isSameOrAfter'
import isSameOrBefore from 'dayjs/plugin/isSameOrBefore'
import LocalizedFormat from 'dayjs/plugin/localizedFormat'
import quarterOfYear from 'dayjs/plugin/quarterOfYear'
import relativeTime from 'dayjs/plugin/relativeTime'
import timezone from 'dayjs/plugin/timezone'
import updateLocale from 'dayjs/plugin/updateLocale'
import utc from 'dayjs/plugin/utc'
import weekOfYear from 'dayjs/plugin/weekOfYear'

// necessary for any localized date formatting to work
dayjs.extend(LocalizedFormat)
dayjs.extend(relativeTime)
dayjs.extend(isSameOrAfter)
dayjs.extend(isSameOrBefore)
dayjs.extend(utc)
dayjs.extend(timezone)
dayjs.extend(duration)
dayjs.extend(quarterOfYear)
dayjs.extend(weekOfYear)
dayjs.extend(updateLocale)

const now = (): Dayjs => dayjs()

export { dayjs, isDayjs, now }

/** Parse UTC datetime string using Day.js, taking into account time zone conversion edge cases. */
export function dayjsUtcToTimezone(
    isoString: string,
    timezone: string,
    explicitOffset = true,
    format?: dayjs.OptionType,
    strict?: boolean
): Dayjs {
    // Strings from the API have the timezone offset set to UTC ("Z" suffix), so they are explicitly non-local.
    // When there's no timezone offset in the string though, Day.js assumes it's a local datetime,
    // which we need to correct - in that case the `explicitOffset` arg should be `false`.
    let datetime = dayjs(isoString, format, strict).utc(!explicitOffset)
    if (!['GMT', 'UTC'].includes(timezone)) {
        datetime = datetime.tz(timezone) // If the target is non-UTC, perform conversion
    }
    return datetime
}

/** Parse local datetime string using Day.js, taking into account time zone conversion edge cases. */
export function dayjsLocalToTimezone(
    isoString: string,
    timezone: string,
    format?: dayjs.OptionType,
    strict?: boolean
): Dayjs {
    let datetime = dayjs(isoString, format, strict)
    if (['GMT', 'UTC'].includes(timezone)) {
        datetime = datetime.utc(true)
    } else {
        datetime = datetime.tz(timezone, true)
    }
    return datetime
}

// The lines below are copied from "node_modules/dayjs/index.ts" to help typescript and typegen.
// We could only use types like "dayjs.OpUnitType", causing errors such as:
// error TS2312: An interface can only extend an object type or intersection of object types with statically known members.

export interface Dayjs extends DayjsOriginal {}

export type UnitTypeShort = 'd' | 'D' | 'M' | 'y' | 'h' | 'm' | 's' | 'ms'

export type UnitTypeLong = 'millisecond' | 'second' | 'minute' | 'hour' | 'day' | 'month' | 'year' | 'date'

export type UnitTypeLongPlural =
    | 'milliseconds'
    | 'seconds'
    | 'minutes'
    | 'hours'
    | 'days'
    | 'months'
    | 'years'
    | 'dates'

export type UnitType = UnitTypeLong | UnitTypeLongPlural | UnitTypeShort

export type OpUnitType = UnitType | 'week' | 'weeks' | 'w'
export type QUnitType = UnitType | 'quarter' | 'quarters' | 'Q'
export type ManipulateType = Exclude<OpUnitType, 'date' | 'dates'>
