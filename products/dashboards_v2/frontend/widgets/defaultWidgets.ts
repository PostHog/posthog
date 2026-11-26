import { lazyWithRetry } from 'lib/utils/retryImport'

import { createChartWidget } from './chart/createChartWidget'
import { markdownSpec } from './markdown/markdownSpec'
import { type WidgetType, defineWidget } from './widgetDefinition'

// The editor pulls in the rich text stack, which a dashboard with no text tile shouldn't download.
const MarkdownWidget = lazyWithRetry(() =>
    import('./markdown/MarkdownWidget').then((module) => ({ default: module.MarkdownWidget }))
)

/**
 * The widget types that ship with dashboards v2, in add menu order. A host can pass these, a subset, or its own, and
 * can build its own chart widget with `createChartWidget` to add kinds of chart and run queries.
 */
export const DEFAULT_WIDGETS: WidgetType[] = [
    createChartWidget(),
    defineWidget({
        ...markdownSpec,
        addTileOptions: [{ label: 'Text', create: () => ({ type: 'markdown', config: { text: '' } }) }],
        Component: MarkdownWidget,
    }),
]
