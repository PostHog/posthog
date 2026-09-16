import { combineUrl } from 'kea-router'

import { InsightSceneSource, InsightShortId } from '~/types'

/** File system types can be subtyped, for example `insight/funnels`. */
function isInsightType(type: unknown): boolean {
    return typeof type === 'string' && (type === 'insight' || type.startsWith('insight/'))
}

/** Tags an insight URL with the surface it was opened from, so `insight viewed` can report it. */
export function withSceneSource(url: string, sceneSource: InsightSceneSource): string {
    return combineUrl(url, {}, { sceneSource }).url
}

/** Same as `withSceneSource`, for a file system entry. Links to anything but an insight are unchanged. */
export function withInsightSceneSource(href: string, type: unknown, sceneSource: InsightSceneSource): string
export function withInsightSceneSource(
    href: string | undefined,
    type: unknown,
    sceneSource: InsightSceneSource
): string | undefined
export function withInsightSceneSource(
    href: string | undefined,
    type: unknown,
    sceneSource: InsightSceneSource
): string | undefined {
    return href && isInsightType(type) ? withSceneSource(href, sceneSource) : href
}

/** The short ID of a file system entry, so insight analytics can join on it. Undefined for anything else. */
export function insightShortIdForEntry(type: unknown, ref: unknown): InsightShortId | undefined {
    return isInsightType(type) && typeof ref === 'string' ? (ref as InsightShortId) : undefined
}
