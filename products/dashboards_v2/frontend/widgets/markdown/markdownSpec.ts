import { z } from 'zod'

import type { WidgetSpec } from '../widgetSpec'

export const markdownConfigSchema = z.strictObject({ text: z.string() })

export type MarkdownConfig = z.infer<typeof markdownConfigSchema>

export const markdownSpec: WidgetSpec<MarkdownConfig> = {
    type: 'markdown',
    addMenuItems: [
        { label: 'Text', create: () => ({ type: 'markdown', config: { text: 'Write notes in **Markdown**.' } }) },
    ],
    size: { w: 8, h: 8, minW: 3, minH: 4 },
    configSchema: markdownConfigSchema,
}
