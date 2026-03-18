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
    'cli',
    'render_query',
]

const projectIdentifierInUrlRegex = /^\/project\/(\d+|phc_)/

function isPathWithoutProjectId(path: string): boolean {
    const firstPart = path.split('/')[1]
    return pathsWithoutProjectId.includes(firstPart)
}

function addProjectIdUnlessPresent(path: string, teamId?: TeamType['id']): string {
    if (path.match(projectIdentifierInUrlRegex)) {
        return path
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
