const UNIT_HOURS: Record<string, number> = {
    h: 1,
    d: 24,
    w: 24 * 7,
    m: 24 * 30,
    y: 24 * 365,
}

const relativeDateToHours = (dateFrom: string | null | undefined): number | null => {
    if (!dateFrom) {
        return null
    }
    const match = /^-(\d+)([hdwmy])$/.exec(dateFrom)
    if (!match) {
        return null
    }
    const amount = parseInt(match[1], 10)
    const unit = match[2]
    return amount * UNIT_HOURS[unit]
}

export type WideningSuggestion = {
    value: string
    label: string
}

// Suggest the next reasonable widening of `date_from` when the playlist returns no matches.
// Graduated instead of a single 30-day jump so users aren't flooded with results when their
// current window is e.g. "Last hour". Mirrors the presets in RecordingsUniversalFiltersEmbed.
export const nextWideningSuggestion = (dateFrom: string | null | undefined): WideningSuggestion | null => {
    const currentHours = relativeDateToHours(dateFrom)
    // Unparseable (e.g. absolute date) — fall back to the original 30-day suggestion so we never regress.
    if (currentHours === null) {
        return { value: '-30d', label: 'Search over the last 30 days' }
    }
    if (currentHours <= UNIT_HOURS.d) {
        return { value: '-7d', label: 'Search over the last 7 days' }
    }
    if (currentHours < UNIT_HOURS.d * 30) {
        return { value: '-30d', label: 'Search over the last 30 days' }
    }
    return null
}
