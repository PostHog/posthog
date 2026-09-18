import type { HrefMatchType } from './heatmapDataLogic'

export type HeatmapUrlMatchMode = 'page' | 'exact'

export interface HeatmapUrlFilter {
    href: string
    matchType: HrefMatchType
    regex: string | null
}

export const escapeUnescapedRegex = (str: string): string =>
    str.replace(/\\.|([.*+?^=!:${}()|[\]/\\])/g, (match, group1) => (group1 ? `\\${group1}` : match))

export const hasWildcard = (url: string): boolean => url.includes('*')

const parseUrl = (url: string): URL | null => {
    try {
        return new URL(url)
    } catch {
        return null
    }
}

const normalizeUrlPath = (urlObj: URL): string => {
    if (urlObj.pathname === '') {
        urlObj.pathname = '/'
    }
    return urlObj.toString()
}

export const heatmapPagePath = (url: string): string | null => {
    const parsed = parseUrl(url.trim())
    return parsed ? parsed.pathname : null
}

export const resolveHeatmapUrlFilter = (
    url: string | null | undefined,
    mode: HeatmapUrlMatchMode = 'exact'
): HeatmapUrlFilter | null => {
    const trimmed = url?.trim()
    if (!trimmed) {
        return null
    }
    if (hasWildcard(trimmed)) {
        const segments = trimmed
            .replace(/^\^|\$$/g, '')
            .replace(/\.\*/g, '*')
            .split('*')
            .map(escapeUnescapedRegex)
        return { href: segments.join('*'), matchType: 'pattern', regex: `^${segments.join('.*')}$` }
    }
    const parsed = parseUrl(trimmed)
    if (!parsed) {
        return null
    }
    if (mode === 'page') {
        const page = `${parsed.origin}${parsed.pathname.replace(/\/+$/, '')}`
        const regex = `^${escapeUnescapedRegex(page)}\\/?(\\?.*)?(#.*)?$`
        return { href: regex, matchType: 'pattern', regex }
    }
    return { href: normalizeUrlPath(parsed), matchType: 'exact', regex: null }
}

export function heatmapUrlPatternToRegex(value: string): string {
    let normalized = value
    if (!normalized.startsWith('^')) {
        normalized = `^${normalized}`
    }
    if (!normalized.endsWith('$')) {
        normalized = `${normalized}$`
    }
    return Array.from(normalized)
        .map((character, index) => (character === '*' && index > 0 && normalized[index - 1] !== '.' ? '.+' : character))
        .join('')
}
