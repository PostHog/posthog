import { RGBColor } from 'd3'

import { FunnelPathsFilter, PathsFilter } from '~/queries/schema/schema-general'
import { FunnelPathType } from '~/types'

import { HIDE_PATH_CARD_HEIGHT } from './Paths'
import { PATH_NODE_CARD_TOP_OFFSET } from './constants'

const PATH_NODE_CARD_TOP_ADJUSTMENTS = 33

export interface PathTargetLink {
    average_conversion_time: number
    index: number
    source: PathNodeData
    target: PathNodeData
    value: number
    width: number
    y0: number
    color: RGBColor
}

export interface PathNodeData {
    name: string
    targetLinks: PathTargetLink[]
    sourceLinks: PathTargetLink[]
    depth: number
    width: number
    height: number
    index: number
    value: number
    x0: number
    x1: number
    y0: number
    y1: number
    layer: number
    source: PathNodeData
    target: PathNodeData
    visible?: boolean
}

export function roundedRect(
    x: number,
    y: number,
    w: number,
    h: number,
    r: number,
    tl: boolean,
    tr: boolean,
    bl: boolean,
    br: boolean
): string {
    let retval
    retval = 'M' + (x + r) + ',' + y
    retval += 'h' + (w - 2 * r)
    if (tr) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + r
    } else {
        retval += 'h' + r
        retval += 'v' + r
    }
    retval += 'v' + (h - 2 * r)
    if (br) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + -r + ',' + r
    } else {
        retval += 'v' + r
        retval += 'h' + -r
    }
    retval += 'h' + (2 * r - w)
    if (bl) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + -r + ',' + -r
    } else {
        retval += 'h' + -r
        retval += 'v' + -r
    }
    retval += 'v' + (2 * r - h)
    if (tl) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + -r
    } else {
        retval += 'v' + -r
        retval += 'h' + r
    }
    retval += 'z'
    return retval
}

export function pageUrl(d: PathNodeData, display?: boolean, showFullUrls?: boolean): string {
    const incomingUrls = d.targetLinks
        .map((l) => l?.source?.name?.replace(/(^[0-9]+_)/, ''))
        .filter((a) => {
            try {
                new URL(a)
            } catch {
                return false
            }
            return a
        })
        .map((a) => new URL(a))
    const incomingDomains = Array.from(new Set(incomingUrls.map((url) => url.origin)))

    let name = d.name.replace(/(^[0-9]+_)/, '')

    if (!display) {
        return name
    }

    try {
        const url = new URL(name)
        name = incomingDomains.length !== 1 ? url.href.replace(/(^\w+:|^)\/\//, '') : url.pathname + url.search
        if (url.hash?.includes('/')) {
            name += url.hash
        }
    } catch {
        // discard if invalid url
    }

    if (showFullUrls) {
        return name
    }
    return name.length > 15
        ? name.substring(0, 6) + '...' + name.slice(-8)
        : name.length < 4 && d.name.length < 25
          ? d.name.replace(/(^[0-9]+_)/, '')
          : name
}

export const isSelectedPathStartOrEnd = (
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    pathItemCard: PathNodeData
): boolean => {
    const cardName = pageUrl(pathItemCard)
    const isPathStart = pathItemCard.targetLinks.length === 0
    const isPathEnd = pathItemCard.sourceLinks.length === 0
    const { startPoint, endPoint } = pathsFilter
    const { funnelPathType, funnelSource, funnelStep } = funnelPathsFilter || {}

    return (
        (startPoint === cardName && isPathStart) ||
        (endPoint === cardName && isPathEnd) ||
        (funnelPathType === FunnelPathType.between &&
            ((cardName === funnelSource?.series[funnelStep! - 1].name && isPathEnd) ||
                (cardName === funnelSource?.series[funnelStep! - 2].name && isPathStart)))
    )
}

export const calculatePathNodeCardTop = (node: PathNodeData, canvasHeight: number): number => {
    const isNodeCutoff = node.y1 - node.y0 < HIDE_PATH_CARD_HEIGHT && node.y1 > canvasHeight - HIDE_PATH_CARD_HEIGHT
    const isPathEnd = node.sourceLinks.length === 0
    const result = !isPathEnd ? node.y0 + PATH_NODE_CARD_TOP_OFFSET : node.y0 + (node.y1 - node.y0) / 2
    if (isNodeCutoff) {
        return result - PATH_NODE_CARD_TOP_ADJUSTMENTS
    }
    return result
}
