import { EventType } from '@posthog/rrweb-types'

import { RecordingSnapshot } from '../types'
import { isObject } from '../utils'

export interface ViewportResolution {
    width: string
    height: string
    href: string
}

export const getHrefFromSnapshot = (snapshot: unknown): string | undefined => {
    return isObject(snapshot) && 'data' in snapshot
        ? (snapshot.data as any)?.href || (snapshot.data as any)?.payload?.href
        : undefined
}

export const extractDimensionsFromMobileSnapshot = (snapshot: RecordingSnapshot): ViewportResolution | undefined => {
    if (snapshot.type !== EventType.FullSnapshot) {
        return undefined
    }

    try {
        const data = snapshot.data as any
        const node = data?.node as any

        if (!node?.childNodes) {
            return undefined
        }

        let htmlElement: any
        for (const child of node.childNodes) {
            if (child.type === 2 && child.tagName === 'html') {
                htmlElement = child
                break
            }
        }

        if (!htmlElement?.childNodes) {
            return undefined
        }

        let bodyElement: any
        for (const child of htmlElement.childNodes) {
            if (child.type === 2 && child.tagName === 'body' && child.attributes?.['data-rrweb-id']) {
                bodyElement = child
                break
            }
        }

        if (!bodyElement?.childNodes) {
            return undefined
        }

        for (const child of bodyElement.childNodes) {
            if (
                child.type === 2 &&
                child.tagName === 'img' &&
                child.attributes?.['data-rrweb-id'] &&
                child.attributes?.width &&
                child.attributes?.height
            ) {
                return {
                    width: String(child.attributes.width),
                    height: String(child.attributes.height),
                    href: data?.href || getHrefFromSnapshot(snapshot) || 'unknown',
                }
            }
        }
    } catch {
        // Silently fail - this is a best-effort extraction
    }

    return undefined
}
