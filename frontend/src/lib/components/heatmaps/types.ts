export type CommonFilters = {
    date_from?: string | null
    date_to?: string | null
    filter_test_accounts?: boolean
}

export type HeatmapKind = 'click' | 'rageclick' | 'mousemove' | 'scrolldepth'

export type HeatmapRequestType = {
    type: HeatmapKind
    date_from?: string
    date_to?: string
    url_exact?: string
    url_pattern?: string
    viewport_width_min?: number
    viewport_width_max?: number
    aggregation: 'total_count' | 'unique_visitors'
}

export type HeatmapFilters = {
    enabled: boolean
    type?: string
    viewportAccuracy?: number
    aggregation?: HeatmapRequestType['aggregation']
}

export type HeatmapJsDataPoint = {
    x: number
    y: number
    value: number
}

export type HeatmapJsData = {
    data: HeatmapJsDataPoint[]
    max: number
    min: number
}

export type HeatmapFixedPositionMode = 'fixed' | 'relative' | 'hidden'
