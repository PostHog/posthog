export interface ChartDataPoint {
    minute: string
    timestamp: number
    users: number
    pageviews: number
}

export interface DeviceBreakdownItem {
    device: string
    count: number
    percentage: number
}

export interface PathItem {
    path: string
    views: number
}

export interface SlidingWindowBucket {
    pageviews: number
    devices: Map<string, Set<string>>
    paths: Map<string, number>
    uniqueUsers: Set<string>
    countries: Map<string, number>
}

export interface CountryBreakdownItem {
    country: string
    count: number
    percentage: number
}

export interface LiveGeoEvent {
    lat: number
    lng: number
    country_code: string
    count: number
}
