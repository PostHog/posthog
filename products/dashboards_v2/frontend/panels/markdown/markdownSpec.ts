import { z } from 'zod'

import type { PanelSpec } from '../panelSpec'

export const markdownConfigSchema = z.strictObject({ text: z.string() })

export type MarkdownConfig = z.infer<typeof markdownConfigSchema>

export const markdownSpec: PanelSpec<MarkdownConfig> = {
    type: 'markdown',
    addMenuItems: [{ label: 'Text', create: () => ({ type: 'markdown', config: { text: '' } }) }],
    size: { w: 8, h: 8, minW: 3, minH: 4 },
    configSchema: markdownConfigSchema,
    appearance: { background: true, backgroundColor: true },
}
