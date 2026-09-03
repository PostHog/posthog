import { sceneConfigurations } from 'scenes/scenes'

import { FileSystemImport } from '~/queries/schema/schema-general'

/**
 * Tree items whose product has no page on posthog.com/docs yet, so they show no docs link.
 * Every other sidebar tool must have one — `sidebarToolMeta.test.ts` fails when a new tool has neither.
 */
export const SIDEBAR_TOOLS_WITHOUT_DOCS = new Set<string>([
    'AI gateway',
    'Apps',
    'Business knowledge',
    'Engineering analytics',
    'Identity matching',
    'Links',
    'Live Debugger',
    'Product tours',
    'Pulse',
    'User research',
    'Visual review',
])

export interface SidebarToolMeta {
    description?: string
    docsHref?: string
}

/** Description and docs link for a sidebar tool, both read from the product's scene config. */
export function sidebarToolMeta(product: FileSystemImport): SidebarToolMeta {
    // Most tree items name their scene explicitly; the rest are generated with a single-scene list.
    const sceneKey = product.sceneKey ?? (product.sceneKeys?.length === 1 ? product.sceneKeys[0] : undefined)
    const sceneConfig = sceneKey ? sceneConfigurations[sceneKey] : undefined
    return { description: sceneConfig?.description, docsHref: sceneConfig?.docsHref }
}
