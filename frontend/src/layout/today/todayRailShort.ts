// Tailwind only reads literal class names, so these repeat TODAY_RAIL_SHORT_MAX_HEIGHT. Keep them in step.
export const TODAY_RAIL_SHORT_MAX_HEIGHT = 840

export const TODAY_RAIL_SHORT_TILE_CLASS = '[@media(max-height:840px)]:gap-0.5'
export const TODAY_RAIL_SHORT_ICON_CLASS = '[@media(max-height:840px)]:h-9'
export const TODAY_RAIL_SHORT_STACK_CLASS = '[@media(max-height:840px)]:gap-2.5'
export const TODAY_RAIL_SHORT_PADDING_CLASS = '[@media(max-height:840px)]:py-2.5'

export interface TodayRailMetrics {
    tileHeight: number
    gap: number
}

export const TODAY_RAIL_METRICS: TodayRailMetrics = { tileHeight: 56, gap: 12 }
export const TODAY_RAIL_SHORT_METRICS: TodayRailMetrics = { tileHeight: 50, gap: 10 }

export function todayRailMetrics(windowHeight: number | undefined): TodayRailMetrics {
    return windowHeight !== undefined && windowHeight <= TODAY_RAIL_SHORT_MAX_HEIGHT
        ? TODAY_RAIL_SHORT_METRICS
        : TODAY_RAIL_METRICS
}
