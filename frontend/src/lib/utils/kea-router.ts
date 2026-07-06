import { TeamType } from '~/types'

import { getCurrentTeamId } from './getAppContext'
import { tryDecodeURIComponent } from './url'

const pathsWithoutProjectId = [
    'api',
    'me',
    'instance',
    'organization',
    'preflight',
    'login',
    'signup',
    'create-organization',
    'account',
    'oauth',
    'shared',
    'embedded',
    'interview',
    'cli',
    'render_query',
]

const projectIdentifierInUrlRegex = /^\/project\/(\d+|phc_)/

function isPathWithoutProjectId(path: string): boolean {
    const firstPart = path.split('/')[1]
    return pathsWithoutProjectId.includes(firstPart)
}

function normalizeRelativePath(path: string): string {
    const normalized = path.replace(/^(\.\.\/|\.\/)+/, '')
    return normalized.startsWith('/') ? normalized : `/${normalized}`
}

function addProjectIdUnlessPresent(path: string, teamId?: TeamType['id']): string {
    if (path.match(projectIdentifierInUrlRegex)) {
        return path
    }

    if (path.startsWith('../') || path.startsWith('./')) {
        path = normalizeRelativePath(path)
    }

    let prefix = ''
    try {
        prefix = `/project/${teamId ?? getCurrentTeamId()}`
        if (path == '/') {
            return prefix
        }
    } catch {
        // Not logged in
    }
    if (path === prefix || path.startsWith(prefix + '/')) {
        return path
    }
    return `${prefix}/${path.startsWith('/') ? path.slice(1) : path}`
}

export function removeProjectIdIfPresent(path: string): string {
    if (path.match(projectIdentifierInUrlRegex)) {
        return '/' + path.split('/').splice(3).join('/')
    }
    return path
}

export function stripTrailingSlash(path: string): string {
    if (path.length > 1 && path.endsWith('/')) {
        return path.replace(/\/+$/, '')
    }
    return path
}

export function removeFlagIdIfPresent(path: string): string {
    if (path.match(/^\/feature_flags\/\d+/)) {
        return path.replace(/(feature_flags).*$/, '$1/')
    }
    return path
}

export function addProjectIdIfMissing(path: string, teamId?: TeamType['id']): string {
    return isPathWithoutProjectId(removeProjectIdIfPresent(path))
        ? removeProjectIdIfPresent(path)
        : addProjectIdUnlessPresent(path, teamId)
}

const STAY_ON_SAME_PAGE_PATHS = ['settings']
const REDIRECT_TO_PROJECT_ROOT_PATHS = ['products', 'onboarding']

// Mirrors kea-router's default `parseValue`: coerce numbers/booleans and parse JSON-looking values.
function parseParamValue(value: string): any {
    if (!Number.isNaN(Number(value)) && value.trim() !== '') {
        return Number(value)
    } else if (value.toLowerCase() === 'true' || value.toLowerCase() === 'false') {
        return value.toLowerCase() === 'true'
    } else if (value.length >= 2 && (value.match(/^\[.*\] +$/) || value.match(/^\{.*\} +$/))) {
        return value.substring(0, value.length - 1)
    } else if (value.length >= 2 && (value.match(/^\[.*\]$/) || value.match(/^\{.*\}$/))) {
        try {
            return JSON.parse(value)
        } catch {
            // Not valid JSON, fall through to returning the raw string
        }
    }
    return value
}

/**
 * Drop-in replacement for kea-router's default `decodeParams` that tolerates malformed
 * percent-encoding. The default uses a raw `decodeURIComponent`, so a dangling `%` in a URL
 * hash (e.g. a truncated pasted link like `#q=...%`) throws `URIError` during router init and
 * crashes the whole app on boot. Using `tryDecodeURIComponent` lets bad params degrade to their
 * raw string instead of taking down the app.
 */
export function decodeParams(input: string, symbol: string): Record<string, any> {
    if (symbol && input.indexOf(symbol) === 0) {
        input = input.slice(1)
    }

    const ret: Record<string, any> = Object.create(null)

    for (let param of input.split('&')) {
        param = param.replace(/\+/g, ' ')
        const index = param.indexOf('=')
        if (index === -1) {
            if (param.length > 0) {
                ret[tryDecodeURIComponent(param)] = null
            }
        } else {
            const key = tryDecodeURIComponent(param.slice(0, index))
            const value = tryDecodeURIComponent(param.slice(index + 1))
            ret[key] = parseParamValue(value)
        }
    }

    return ret
}

export function getProjectSwitchTargetUrl(
    currentPath: string,
    newTeamId: number,
    currentProjectId?: number | null,
    newProjectId?: number | null
): string {
    // Remove project ID and flag ID from the path
    let route = removeProjectIdIfPresent(currentPath)
    route = removeFlagIdIfPresent(route)

    // Extract the resource path (first part after removing project ID)
    const resourcePath = route.split('/')[1]

    // If it's a path that should redirect to project root
    if (REDIRECT_TO_PROJECT_ROOT_PATHS.includes(resourcePath)) {
        return `/project/${newTeamId}`
    }

    // If it's a path where we should stay on the same page (like settings)
    if (STAY_ON_SAME_PAGE_PATHS.includes(resourcePath)) {
        return `/project/${newTeamId}${route}`
    }

    // For other paths with subresources (like /insights/abc123)
    const pathParts = route.split('/')
    if (pathParts.length > 2) {
        // If switching between teams in the same project, keep the resource ID
        if (currentProjectId && newProjectId && currentProjectId === newProjectId) {
            return `/project/${newTeamId}${route}`
        }
        // Otherwise, go to the parent resource
        return `/project/${newTeamId}/${pathParts[1]}`
    }

    // Default: keep the same route structure but with new project ID
    return `/project/${newTeamId}${route}`
}
