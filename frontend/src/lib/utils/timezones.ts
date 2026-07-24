import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'

/**
 * Return the short timezone identifier for a specific timezone (e.g. BST, EST, PDT, UTC+2).
 * @param timeZone E.g. 'America/New_York'
 * @param atDate
 */
export function shortTimeZone(timeZone?: string, atDate?: Date): string | null {
    const date = atDate ? new Date(atDate) : new Date()
    try {
        const localeTimeStringParts = date
            .toLocaleTimeString('en-us', { timeZoneName: 'short', timeZone: timeZone || undefined })
            .replace('GMT', 'UTC')
            .split(' ')
        return localeTimeStringParts[localeTimeStringParts.length - 1]
    } catch (e) {
        posthog.captureException(e)
        return null
    }
}

/** The viewer's own IANA timezone (e.g. 'America/New_York'), as resolved by the browser. */
export function getLocalTimeZone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
}

export function timeZoneLabel(timeZone: string | undefined, offset: number): string {
    if (!timeZone) {
        return ''
    }
    const formattedZone = timeZone.replace(/\//g, ' / ').replace(/_/g, ' ')
    const sign = offset === 0 ? '±' : offset > 0 ? '+' : '-'
    const hours = Math.floor(Math.abs(offset))
    const minutes = Math.round((Math.abs(offset) % 1) * 60)
        .toString()
        .padStart(2, '0')

    return `${formattedZone} (UTC${sign}${hours}:${minutes})`
}

export function humanTzOffset(timezone?: string): string {
    const offset = dayjs().tz(timezone).utcOffset() / 60
    if (!offset) {
        return 'no offset'
    }
    const absoluteOffset = Math.abs(offset)
    const hourForm = absoluteOffset === 1 ? 'hour' : 'hours'
    const direction = offset > 0 ? 'ahead' : 'behind'
    return `${absoluteOffset} ${hourForm} ${direction}`
}
