// Chart
export const VIEW_BOX_WIDTH = 800
export const SVG_EDGE_MARGIN = 20

// ChartCell
export const CHART_CELL_VIEW_BOX_HEIGHT = 51
export const CHART_CELL_BAR_HEIGHT_PERCENT = 15
export const CELL_HEIGHT = 51
export const EMPTY_STATE_ROW_MIN_HEIGHT = 80
export const CHART_BAR_OPACITY = 0.9
export const GRID_LINES_OPACITY = 0.8

// Significant-result highlight: hex alpha suffixes appended to BAR_POSITIVE / BAR_NEGATIVE.
// The row tint must stay dimmer than the win probability / p-value cell so that cell still stands out.
export const SIGNIFICANT_CELL_BG_ALPHA = '30'
export const SIGNIFICANT_ROW_BG_ALPHA = '14'

// Axis
export const TICK_PANEL_HEIGHT = 20
export const TICK_FONT_SIZE = 11
export const MAX_AXIS_RANGE = 1.5 // Cap at ±150% to prevent outliers from squishing other charts
