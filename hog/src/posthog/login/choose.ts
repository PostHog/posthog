import { EXIT_USAGE, HogError } from '@/core/errors'
import type { LoginTarget } from '@/posthog/credential-store/item-name'
import type { Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'
import { hostFlag } from '@/posthog/scope-challenge'
import { latestLoginFor, loginFor, loginsFor, type HogSettings, type LoginRecord } from '@/posthog/settings'

// What names the login a command uses. `host` is --host or HOG_HOST, and `projectId` is
// HOG_PROJECT_ID. Both replace what the closest posthog.json says.
export interface LoginQuery {
    host?: Host
    projectId?: ProjectId
    configPath?: string
    configHost?: Host
    configProjectId?: ProjectId
}

// `exact`: posthog.json names the project, and hog uses the login for that host and project.
// `override`: the same, after --host, HOG_HOST or HOG_PROJECT_ID replaced what posthog.json says.
// `fallback`: nothing names a project, so hog uses the latest login to the host.
export type LoginMatch = 'exact' | 'override' | 'fallback'

// Why a command uses the login it uses. `hog auth status` reports it.
export interface LoginChoice {
    // Null when nothing names a host and hog has no login.
    host: Host | null
    // Null when nothing names a project.
    projectId: ProjectId | null
    match: LoginMatch
    reason: string
}

export interface ChosenLogin {
    choice: LoginChoice
    record: LoginRecord | undefined
}

function reasonFor(query: LoginQuery, host: Host, projectId: ProjectId | undefined): string {
    if (projectId === undefined) {
        return `nothing sets a project in posthog.json or HOG_PROJECT_ID, so hog uses your latest login to ${host}`
    }
    const hostFrom =
        query.host !== undefined ? '--host or HOG_HOST' : query.configHost !== undefined ? 'posthog.json' : undefined
    const projectFrom = query.projectId !== undefined ? 'HOG_PROJECT_ID' : 'posthog.json'
    if (hostFrom === projectFrom) {
        return `${projectFrom} sets the host and the project`
    }
    const hostPart = hostFrom ? `${hostFrom} sets the host` : 'the host is the one you last logged in to'
    return `${projectFrom} sets the project, and ${hostPart}`
}

export function chooseLogin(settings: HogSettings, query: LoginQuery): ChosenLogin {
    const host = query.host ?? query.configHost ?? settings.host
    const projectId = query.projectId ?? query.configProjectId
    const overridden = query.host !== undefined || query.projectId !== undefined
    const choice: LoginChoice = {
        host: host ?? null,
        projectId: projectId ?? null,
        match: projectId === undefined ? 'fallback' : overridden ? 'override' : 'exact',
        reason: host === undefined ? 'hog has no login' : reasonFor(query, host, projectId),
    }
    if (host === undefined) {
        return { choice, record: undefined }
    }
    const record = projectId === undefined ? latestLoginFor(settings, host) : loginFor(settings, { host, projectId })
    return { choice, record }
}

function projectList(projectIds: readonly string[]): string {
    return projectIds.length === 1 ? `project ${projectIds[0]}` : `projects ${projectIds.join(', ')}`
}

// For a host and project that something names, when hog has logins, but none for that pair.
export class ProjectMismatch extends HogError {
    readonly command: string

    constructor(
        query: LoginQuery,
        readonly target: LoginTarget,
        settings: HogSettings
    ) {
        const namedBy = query.projectId !== undefined ? 'HOG_PROJECT_ID' : (query.configPath ?? 'posthog.json')
        const others = loginsFor(settings, target.host)
            .map((record) => record.projectId)
            .sort()
        const loggedIn = others.length > 0 ? ` You're logged in to ${projectList(others)} there.` : ''
        const command = `hog auth login${hostFlag(target.host)}`
        super(
            'project_mismatch',
            `${namedBy} names project ${target.projectId} on ${target.host}, and hog has no login for it.${loggedIn}`,
            `Run \`${command}\` and pick project ${target.projectId} on the approval page. Each project keeps its own login.`,
            EXIT_USAGE,
            { configPath: query.configPath ?? null, host: target.host, projectId: target.projectId, command }
        )
        this.command = command
    }
}
