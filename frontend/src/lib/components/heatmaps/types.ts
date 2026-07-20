export type CommonFilters = {
    date_from?: string | null
    date_to?: string | null
    filter_test_accounts?: boolean
    cohort_ids?: number[]
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

export type HeatmapBounds = {
    left: number
    right: number
    top: number
    bottom: number
}

// pixel bounds of a page element the heatmap is filtered to. Fixed/sticky targets are
// recorded in viewport coordinates and everything else in document coordinates (posthog-js's
// target_fixed rule), so points are only comparable to an area of the same kind: a filter
// carries the one rect that matches its area's kind, and points of the other kind are
// excluded rather than compared across coordinate spaces (where they'd go stale on scroll)
export type HeatmapBoundsFilter = {
    bounds: HeatmapBounds
    areaFixed: boolean
}

export type HeatmapAreaPoint = {
    x: number
    y: number
    target_fixed: boolean
}

export type HeatmapArea = {
    points: HeatmapAreaPoint[]
    expectedCount: number
    clickX: number
    clickY: number
}

export type HeatmapEvent = {
    session_id: string | null
    distinct_id: string
    timestamp: string
    pointer_relative_x: number
    pointer_y: number
    current_url: string
    type: string
}

export type HeatmapEventsResponse = {
    results: HeatmapEvent[]
    total_count: number
    has_more: boolean
}
