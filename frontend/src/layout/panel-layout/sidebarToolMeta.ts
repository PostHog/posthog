import { commandDescriptions } from 'lib/components/Search/commandDescriptions'
import { sceneConfigurations } from 'scenes/scenes'

import { FileSystemImport } from '~/queries/schema/schema-general'

/**
 * Tree items whose product has no page on posthog.com/docs yet, so they show no docs link.
 * Every other sidebar tool must have one — `sidebarToolMeta.test.ts` fails when a new tool has neither.
 */
export const SIDEBAR_TOOLS_WITHOUT_DOCS = new Set<string>([
    'AI gateway',
    'Apps',
    'Broadcasts',
    'Business knowledge',
    'Engineering analytics',
    'Identity matching',
    'Links',
    'Live Debugger',
    'Product tours',
    'Pulse',
    'User research',
    'Visual review',
    'Wizard',
])

export interface SidebarToolMeta {
    description?: string
    docsHref?: string
}

/** Shared descriptions for app tooltips and sidebar settings, with docs from the scene config. */
export function sidebarToolMeta(product: FileSystemImport): SidebarToolMeta {
    // Most tree items name their scene explicitly; the rest are generated with a single-scene list.
    const sceneKey = product.sceneKey ?? (product.sceneKeys?.length === 1 ? product.sceneKeys[0] : undefined)
    const sceneConfig = sceneKey ? sceneConfigurations[sceneKey] : undefined
    const isGroup =
        product.iconType === 'group' || product.iconType?.startsWith('group_') || product.type?.startsWith('group_')
    return {
        // Group paths come from configurable group type names, which can match a built-in app name.
        description: isGroup
            ? 'Explore the organizations, accounts, or other groups behind your events. Understand usage at the group level.'
            : (commandDescriptions[product.path] ?? sceneConfig?.description),
        docsHref: sceneConfig?.docsHref,
    }
}
