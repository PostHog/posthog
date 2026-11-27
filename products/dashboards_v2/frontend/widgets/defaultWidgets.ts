import { createChartWidget } from './chart/createChartWidget'
import type { WidgetType } from './core/widgetDefinition'
import { markdownWidget } from './markdown/markdownSpec'

/**
 * The widget types that ship with dashboards v2, in add menu order. A host can pass these, a subset, or its own, and
 * can build its own chart widget with `createChartWidget` to add kinds of chart and run queries.
 */
export const DEFAULT_WIDGETS: WidgetType[] = [createChartWidget(), markdownWidget]
