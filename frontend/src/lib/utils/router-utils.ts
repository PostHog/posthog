import { TeamType } from '~/types'

import { getCurrentTeamId } from './getAppContext'

const pathsWithoutProjectId = ['api', 'me', 'instance', 'organization', 'preflight', 'login', 'signup']

function isPathWithoutProjectId(path: string): boolean {
    const firstPart = path.split('/')[1]
    return pathsWithoutProjectId.includes(firstPart)
}

function addProjectIdUnlessPresent(path: string, teamId: TeamType['id'] | ':teamId'): string {
    if (path.match(/^\/project\/\d+/)) {
        return path
    }

    let prefix = ''
    try {
        prefix = `/project/${teamId}`
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

export function addProjectIdIfMissing(path: string, teamId?: TeamType['id'] | ':teamId'): string {
    return isPathWithoutProjectId(removeProjectIdIfPresent(path))
        ? removeProjectIdIfPresent(path)
        : addProjectIdUnlessPresent(path, teamId ?? getCurrentTeamId())
}
