import { z } from 'zod'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { defineWidget } from '../core/widgetDefinition'
import type { WidgetSpec } from '../core/widgetSpec'

export const markdownConfigSchema = z.strictObject({ text: z.string() })

export type MarkdownConfig = z.infer<typeof markdownConfigSchema>

export const markdownSpec: WidgetSpec<MarkdownConfig, 'markdown'> = {
    type: 'markdown',
    size: { w: 8, h: 8, minW: 3, minH: 4 },
    configSchema: markdownConfigSchema,
    allowedCustomizations: ['backgroundColor'],
}

// The editor pulls in the rich text stack, which a dashboard with no text tile shouldn't download.
const MarkdownWidget = lazyWithRetry(() =>
    import('./MarkdownWidget').then((module) => ({ default: module.MarkdownWidget }))
)

export const markdownWidget = defineWidget({
    ...markdownSpec,
    addTileOptions: [{ label: 'Text', create: () => ({ type: 'markdown', config: { text: '' } }) }],
    Component: MarkdownWidget,
})
