import { humanFriendlyDuration } from 'lib/utils/durations'

const AUTO_REFRESH_INTERVAL_SECONDS = [900, 1800, 3600]
if (process.env.NODE_ENV === 'development') {
    AUTO_REFRESH_INTERVAL_SECONDS.unshift(10)
}

export const AUTO_REFRESH_INTERVAL_OPTIONS = AUTO_REFRESH_INTERVAL_SECONDS.map((value) => ({
    label: humanFriendlyDuration(value),
    value,
}))
