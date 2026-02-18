export interface ChartDataPoint {
    minute: string
    timestamp: number
    users: number
    newUsers: number
    returningUsers: number
    pageviews: number
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

export interface SlidingWindowBucket {
    pageviews: number
    devices: Map<string, Set<string>>
    browsers: Map<string, Set<string>>
    paths: Map<string, number>
    uniqueUsers: Set<string>
}
