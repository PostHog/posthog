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
    devices: Map<string, number>
    paths: Map<string, number>
    uniqueUsers: Set<string>
}
