// eslint-disable-next-line no-restricted-imports
import dayjs, { Dayjs as DayjsOriginal } from 'dayjs'
import LocalizedFormat from 'dayjs/plugin/localizedFormat'
import relativeTime from 'dayjs/plugin/relativeTime'
import isSameOrAfter from 'dayjs/plugin/isSameOrAfter'
import isSameOrBefore from 'dayjs/plugin/isSameOrBefore'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import duration from 'dayjs/plugin/duration'

// necessary for any localized date formatting to work
dayjs.extend(LocalizedFormat)
dayjs.extend(relativeTime)
dayjs.extend(isSameOrAfter)
dayjs.extend(isSameOrBefore)
dayjs.extend(utc)
dayjs.extend(timezone)
dayjs.extend(duration)

const now = (): Dayjs => dayjs()

export { dayjs, now }

// The lines below are copied from "node_modules/dayjs/index.ts" to help typescript and typegen.
// We could only use types like "dayjs.OpUnitType", causing errors such as:
// error TS2312: An interface can only extend an object type or intersection of object types with statically known members.

// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface Dayjs extends DayjsOriginal {}

export type UnitTypeShort = 'd' | 'M' | 'y' | 'h' | 'm' | 's' | 'ms'

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
export type ManipulateType = Omit<OpUnitType, 'date' | 'dates'>
