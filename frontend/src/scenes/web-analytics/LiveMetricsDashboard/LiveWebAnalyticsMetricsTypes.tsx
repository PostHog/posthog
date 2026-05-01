export interface ChartDataPoint {
    minute: string
    timestamp: number
    users: number
    newUsers: number
    returningUsers: number
    pageviews: number
    botEvents: number
}

export interface DeviceBreakdownItem {
    device: string
    count: number
    percentage: number
}

export interface BrowserBreakdownItem {
    browser: string
    count: number
    percentage: number
}

export interface PathItem {
    path: string
    views: number
}

export const DIRECT_REFERRER = '$direct'

export interface ReferrerItem {
    referrer: string
    views: number
}

export interface SlidingWindowBucket {
    pageviews: number
    // Total events of the bot-eligible types (the 5 events the bot detector classifies).
    // Used as the denominator for "% of total" on the bot traffic tile.
    botEligibleEvents: number
    newUserCount: number
    returningUserCount: number
    devices: Map<string, Set<string>>
    browsers: Map<string, Set<string>>
    paths: Map<string, number>
    referrers: Map<string, number>
    uniqueUsers: Set<string>
    countries: Map<string, Set<string>>
    // Optional to keep existing test fixtures and backfill helpers concise. Keyed via `buildCityKey`.
    cities?: Map<string, Set<string>>
    // Optional so that existing tests and backfill helpers don't have to
    // construct bot maps when they are not asserting on bot traffic.
    bots?: Map<string, { count: number; category: string }>
}

export const BOT_KEY_SEPARATOR = '|||'

export const BOT_ELIGIBLE_EVENTS = ['$pageview', '$pageleave', '$screen', '$http_log', '$autocapture'] as const

export const buildBotKey = (botName: string, category: string): string => `${botName}${BOT_KEY_SEPARATOR}${category}`

export const parseBotKey = (key: string): { botName: string; category: string } => {
    const sepIdx = key.indexOf(BOT_KEY_SEPARATOR)
    if (sepIdx === -1) {
        return { botName: key, category: '' }
    }
    return { botName: key.slice(0, sepIdx), category: key.slice(sepIdx + BOT_KEY_SEPARATOR.length) }
}

export interface BotBreakdownItem {
    bot: string
    category: string
    count: number
    percentage: number
}

export interface CountryBreakdownItem {
    country: string
    count: number
    percentage: number
}

export interface CityBreakdownItem {
    cityName: string
    countryCode: string
    count: number
    percentage: number
}

export const CITY_KEY_SEPARATOR = '|'

export const buildCityKey = (cityName: string, countryCode: string): string =>
    `${cityName}${CITY_KEY_SEPARATOR}${countryCode}`

export const parseCityKey = (key: string): { cityName: string; countryCode: string } => {
    const sepIdx = key.lastIndexOf(CITY_KEY_SEPARATOR)
    if (sepIdx === -1) {
        return { cityName: key, countryCode: '' }
    }
    return { cityName: key.slice(0, sepIdx), countryCode: key.slice(sepIdx + 1) }
}

export interface LiveGeoEvent {
    countryCode: string
    distinctId: string
}
