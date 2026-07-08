// oxlint-disable-next-line no-restricted-imports
import dayjs, { Dayjs as DayjsOriginal, isDayjs } from 'dayjs'
import advancedFormat from 'dayjs/plugin/advancedFormat'
import customParseFormat from 'dayjs/plugin/customParseFormat'
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

dayjs.extend(advancedFormat)
// necessary for parsing custom date formats like 'YYYYMMDD_HHmmss'
dayjs.extend(customParseFormat)
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

// The base add/subtract accept ManipulateType (has week, no quarter) and the quarterOfYear plugin
// adds a QUnitType overload (has quarter, no week). Neither alone accepts a union spanning both
// (e.g. IntervalType), so merge one overload that takes both. Casting to a single side instead
// would be unsound: `x as QUnitType` lies when x is 'week'. Types are declared lower in this file.
declare module 'dayjs' {
    interface Dayjs {
        add(value: number, unit?: ManipulateType | QUnitType): DayjsOriginal
        subtract(value: number, unit?: ManipulateType | QUnitType): DayjsOriginal
    }
}

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

/** Current moment expressed as the given timezone's wall clock, returned as a naive (offset-free) Dayjs
 *  so it stays comparable to naive picked datetimes. Falls back to browser-local time on an invalid timezone. */
export function dayjsNowInTimezone(timezone: string): Dayjs {
    try {
        return dayjs(dayjs().tz(timezone).format('YYYY-MM-DDTHH:mm:ss.SSS'))
    } catch {
        return dayjs()
    }
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
