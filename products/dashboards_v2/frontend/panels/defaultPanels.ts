import { lazyWithRetry } from 'lib/utils/retryImport'

import { createChartPanel } from './chart/createChartPanel'
import { markdownSpec } from './markdown/markdownSpec'
import { type PanelDefinition, definePanel } from './panelDefinition'

// The editor pulls in the rich text stack, which a dashboard with no text tile shouldn't download.
const MarkdownPanel = lazyWithRetry(() =>
    import('./markdown/MarkdownPanel').then((module) => ({ default: module.MarkdownPanel }))
)

/**
 * The panel types that ship with dashboards v2, in add menu order. A host can pass these, a subset, or its own, and
 * can build its own chart panel with `createChartPanel` to add kinds of chart and run queries.
 */
export const DEFAULT_PANELS: PanelDefinition[] = [
    createChartPanel(),
    definePanel({ ...markdownSpec, Component: MarkdownPanel }),
]
