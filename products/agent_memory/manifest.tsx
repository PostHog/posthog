import { ProductManifest } from '~/types'

// Agent memory has no human-facing scenes of its own yet — it's an agent-and-API
// surface (REST + MCP) consumed by the signals scouts, scouts UI, and Slack agents.
export const manifest: ProductManifest = {
    name: 'Agent memory',
    treeItemsNew: [],
    treeItemsProducts: [],
}
