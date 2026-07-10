import { TeamType } from '~/types'

import { getCurrentTeamId } from './getAppContext'

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

// Instance-level pages that live under a product's own path prefix rather than
// under `/instance/*`, so they need an exact (rather than first-segment) exemption.
const exactPathsWithoutProjectId = ['/feature_flags/staff']

const projectIdentifierInUrlRegex = /^\/project\/(\d+|phc_)/

function isPathWithoutProjectId(path: string): boolean {
    const pathname = path.split(/[?#]/)[0]
    if (
        exactPathsWithoutProjectId.some((exactPath) => pathname === exactPath || pathname.startsWith(exactPath + '/'))
    ) {
        return true
    }
    const firstPart = pathname.split('/')[1]
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

// Beta, flag-gated products whose scenes render <NotFound> when the gating flag is off. The flag
// is evaluated per project, so a product can be enabled in the current project but disabled in the
// target one, and the switcher has no way to know the target project's flags before navigating.
// Resource IDs under these routes (e.g. a scanner UUID) also don't exist in another environment.
// Rather than risk landing on "Page not found", fall back to the new project's home. Add the
// first URL segment of any such product here.
const FLAG_GATED_PRODUCT_PATHS = ['replay-vision']

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

    // Fall back to the new project's home when the mapped destination wouldn't resolve there:
    // - project-less pages (org/instance/account/...) get stripped back to a routeless bare path
    //   by `locationChanged`, landing on "Page not found"
    // - `products`/`onboarding` are meant to start from the project root anyway
    // - beta, flag-gated products may render <NotFound> if their flag is off in the target project
    if (
        REDIRECT_TO_PROJECT_ROOT_PATHS.includes(resourcePath) ||
        FLAG_GATED_PRODUCT_PATHS.includes(resourcePath) ||
        isPathWithoutProjectId(route)
    ) {
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
