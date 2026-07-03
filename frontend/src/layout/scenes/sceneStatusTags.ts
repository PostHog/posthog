import { getTreeItemsProducts } from '~/products'

export type ProductStatusTag = 'alpha' | 'beta'

// Special navbar entries that carry a status tag but aren't part of the product tree
// (getTreeItemsProducts), so they can't be derived from a manifest.
const EXTRA_SCENE_STATUS_TAGS: Record<string, ProductStatusTag> = {
    Inbox: 'beta',
}

let sceneStatusTagMap: Record<string, ProductStatusTag> | null = null

function buildSceneStatusTagMap(): Record<string, ProductStatusTag> {
    const map: Record<string, ProductStatusTag> = { ...EXTRA_SCENE_STATUS_TAGS }
    for (const item of getTreeItemsProducts()) {
        const tag = item.tags?.[0]
        if (!tag) {
            continue
        }
        const sceneKeys = item.sceneKeys ?? (item.sceneKey ? [item.sceneKey] : [])
        for (const sceneKey of sceneKeys) {
            // First registration wins, so an explicit override above isn't clobbered by a manifest.
            if (!(sceneKey in map)) {
                map[sceneKey] = tag
            }
        }
    }
    return map
}

/**
 * The status tag ('alpha' | 'beta') a scene should show next to its title, mirroring how the same
 * product/tool is tagged in the navbar. Returns undefined for stable products and unknown scenes.
 */
export function getSceneStatusTag(sceneId: string | null | undefined): ProductStatusTag | undefined {
    if (!sceneId) {
        return undefined
    }
    if (!sceneStatusTagMap) {
        sceneStatusTagMap = buildSceneStatusTagMap()
    }
    return sceneStatusTagMap[sceneId]
}
