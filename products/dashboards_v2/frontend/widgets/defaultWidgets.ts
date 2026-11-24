import { createChartWidget } from './chart/createChartWidget'
import { markdownSpec } from './markdown/markdownSpec'
import { MarkdownWidget } from './markdown/MarkdownWidget'
import { type WidgetDefinition, defineWidget } from './widgetDefinition'

/**
 * The widget types that ship with dashboards v2, in add menu order. A host can pass these, a subset, or its own, and
 * can build its own chart widget with `createChartWidget` to add kinds of chart and run queries.
 */
export const DEFAULT_WIDGETS: WidgetDefinition[] = [
    createChartWidget(),
    defineWidget({ ...markdownSpec, Component: MarkdownWidget }),
]
