import { z } from 'zod'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { definePanel } from '../core/panelDefinition'
import type { PanelSpec } from '../core/panelSpec'

export const markdownConfigSchema = z.strictObject({ text: z.string() })

export type MarkdownConfig = z.infer<typeof markdownConfigSchema>

export const markdownSpec: PanelSpec<MarkdownConfig, 'markdown'> = {
    type: 'markdown',
    size: { w: 8, h: 8, minW: 3, minH: 4 },
    configSchema: markdownConfigSchema,
    allowedCustomizations: ['backgroundColor'],
}

// The editor pulls in the rich text stack, which a dashboard with no text tile shouldn't download.
const MarkdownPanel = lazyWithRetry(() =>
    import('./MarkdownPanel').then((module) => ({ default: module.MarkdownPanel }))
)

export const markdownPanel = definePanel({
    ...markdownSpec,
    addTileOptions: [{ label: 'Text', create: () => ({ type: 'markdown', config: { text: '' } }) }],
    Component: MarkdownPanel,
})
