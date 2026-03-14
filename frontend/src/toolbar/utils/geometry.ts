import { ElementRect } from '~/toolbar/core/types'

export function inBounds(min: number, value: number, max: number): number {
    return Math.max(min, Math.min(max, value))
}

export function rectEqual(a?: ElementRect, b?: ElementRect): boolean {
    if (a === b) {
        return true
    }
    if (!a || !b) {
        return false
    }
    return a.top === b.top && a.left === b.left && a.right === b.right && a.bottom === b.bottom
}

export const EMPTY_STYLE: Record<string, any> = {}

export function getRectForElement(element: HTMLElement): ElementRect {
    const elements = [elementToAreaRect(element)]

    let loopElement = element
    while (loopElement.children.length === 1) {
        loopElement = loopElement.children[0] as HTMLElement
        elements.push(elementToAreaRect(loopElement))
    }

    let maxArea = 0
    let maxRect = elements[0].rect

    for (const { rect, area } of elements) {
        if (area >= maxArea) {
            maxArea = area
            maxRect = rect
        }
    }

    return maxRect
}

let zoomCache = new WeakMap<HTMLElement, number[]>()
let pageUsesZoom: boolean | undefined

export function invalidateZoomCache(): void {
    pageUsesZoom = undefined
    zoomCache = new WeakMap()
}

export const getZoomLevel = (el: HTMLElement): number[] => {
    if (pageUsesZoom === false) {
        return []
    }

    const cached = zoomCache.get(el)
    if (cached !== undefined) {
        return cached
    }

    const zooms: number[] = []
    const getZoom = (current: HTMLElement): void => {
        const zoom = window.getComputedStyle(current).getPropertyValue('zoom')
        const rzoom = zoom ? parseFloat(zoom) : 1
        if (rzoom !== 1) {
            zooms.push(rzoom)
        }
        if (current.parentElement?.parentElement) {
            getZoom(current.parentElement)
        }
    }
    getZoom(el)
    zooms.reverse()

    if (zooms.length > 0) {
        pageUsesZoom = true
    }

    zoomCache.set(el, zooms)
    return zooms
}
export const getRect = (el: HTMLElement): ElementRect => {
    if (!el) {
        return { x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0 }
    }
    const rect = el?.getBoundingClientRect()
    const zooms = getZoomLevel(el)
    const rectWithZoom: ElementRect = {
        bottom: zooms.reduce((a, b) => a * b, rect.bottom),
        height: zooms.reduce((a, b) => a * b, rect.height),
        left: zooms.reduce((a, b) => a * b, rect.left),
        right: zooms.reduce((a, b) => a * b, rect.right),
        top: zooms.reduce((a, b) => a * b, rect.top),
        width: zooms.reduce((a, b) => a * b, rect.width),
        x: zooms.reduce((a, b) => a * b, rect.x),
        y: zooms.reduce((a, b) => a * b, rect.y),
    }
    return rectWithZoom
}

function elementToAreaRect(element: HTMLElement): { element: HTMLElement; rect: ElementRect; area: number } {
    const rect = getRect(element)
    return {
        element,
        rect,
        area: (rect.width ?? 0) * (rect.height ?? 0),
    }
}
