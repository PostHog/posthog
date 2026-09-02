/**
 * Product manifest for APM.
 *
 * No scenes or nav entries yet. APM's first deliverable is a backend detector
 * that the logs, tracing, and metrics products consume, so today its only
 * surfaces are theirs. An empty manifest is valid in the meantime; see
 * products/notifications for the same shape.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'APM',
    scenes: {},
    routes: {},
    redirects: {},
    urls: {},
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
