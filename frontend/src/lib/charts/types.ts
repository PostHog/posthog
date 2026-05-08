export type AxisFormat = 'number' | 'compact' | 'percent' | 'duration' | 'duration_ms' | 'date' | 'datetime' | 'none'

// `ChartTheme` is owned by `lib/hog-charts`; re-exported here so existing
// `lib/charts/utils/theme` consumers continue to work during the migration.
export type { ChartTheme } from 'lib/hog-charts'
