import dayjs from '../../lib/dayjs'

export function formatSessionId(session_id: string | number): number {
  // Timestamps may be on a `string` field, so check if the string is only
  // numbers. If it is, convert it into a Number since it's probably already a unix timestamp.
  // DayJS doesn't parse unix timestamps correctly outside of the `.unix()`
  // initializer.
  if (typeof session_id === 'string' && /^\d+$/.test(session_id)) {
    return Number(session_id)
  }
  return dayjs.utc(session_id).valueOf()
}
