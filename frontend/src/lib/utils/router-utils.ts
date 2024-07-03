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
]

function isPathWithoutProjectId(path: string): boolean {
    const firstPart = path.split('/')[1]
    return pathsWithoutProjectId.includes(firstPart)
}

function addProjectIdUnlessPresent(path: string, teamId?: TeamType['id']): string {
    if (path.match(/^\/project\/\d+/)) {
        return path
    }

    let prefix = ''
    try {
        prefix = `/project/${teamId ?? getCurrentTeamId()}`
        if (path == '/') {
            return prefix
        }
    } catch (e) {
        // Not logged in
    }
    if (path === prefix || path.startsWith(prefix + '/')) {
        return path
    }
    return `${prefix}/${path.startsWith('/') ? path.slice(1) : path}`
}

export function removeProjectIdIfPresent(path: string): string {
    if (path.match(/^\/project\/\d+/)) {
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
