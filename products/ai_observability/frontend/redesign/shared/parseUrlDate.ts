import { dayjs } from 'lib/dayjs'

// An unencoded `+` in a URL query decodes to a space, so `+00:00` arrives as ` 00:00`.
export function parseUrlDate(value: string): string | null {
    const raw = String(value).trim()
    if (dayjs(raw).isValid()) {
        return raw
    }
    const repaired = raw.replace(/ (\d{2}:?\d{2})$/, '+$1')
    return dayjs(repaired).isValid() ? repaired : null
}
