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
    newUserCount: number
    returningUserCount: number
    devices: Map<string, Set<string>>
    browsers: Map<string, Set<string>>
    paths: Map<string, number>
    referrers: Map<string, number>
    uniqueUsers: Set<string>
    countries: Map<string, Set<string>>
    // Optional so that existing tests and backfill helpers don't have to
    // construct bot maps when they are not asserting on bot traffic.
    bots?: Map<string, { count: number; category: string }>
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

export interface LiveGeoEvent {
    countryCode: string
    distinctId: string
}
