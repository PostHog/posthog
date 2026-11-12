import { EXIT_USAGE, HogError } from '@/core/errors'
import type { LoginTarget } from '@/posthog/credential-store/item-name'
import { sameHost, type Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'
import { hostFlag } from '@/posthog/scope-challenge'
import {
    fallbackHost,
    latestLoginFor,
    loginFor,
    loginsFor,
    type HogSettings,
    type LoginRecord,
} from '@/posthog/settings'

// `host` comes from --host or HOG_HOST, and `projectId` from HOG_PROJECT_ID. Both override the closest
// posthog.json.
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

export interface LoginChoice {
    host: Host | null
    projectId: ProjectId | null
    match: LoginMatch
    reason: string
}

export interface ChosenLogin {
    choice: LoginChoice
    record: LoginRecord | undefined
}

type HostSource = '--host or HOG_HOST' | 'posthog.json' | 'the latest login'
type ProjectSource = 'HOG_PROJECT_ID' | 'posthog.json' | 'nothing' | 'posthog.json on another host'

interface Sources {
    host: HostSource
    project: ProjectSource
    projectId: ProjectId | undefined
}

// Where the host and the project come from. A project ID means a project on one host, so
// posthog.json's project counts only on its own host.
function sourcesFor(query: LoginQuery, host: Host | undefined): Sources {
    const hostSource =
        query.host !== undefined
            ? '--host or HOG_HOST'
            : query.configHost !== undefined
              ? 'posthog.json'
              : 'the latest login'

    if (query.projectId !== undefined) {
        return { host: hostSource, project: 'HOG_PROJECT_ID', projectId: query.projectId }
    }

    const { configHost, configProjectId } = query
    if (host === undefined || configProjectId === undefined) {
        return { host: hostSource, project: 'nothing', projectId: undefined }
    }

    return configHost === undefined || sameHost(configHost, host)
        ? { host: hostSource, project: 'posthog.json', projectId: configProjectId }
        : { host: hostSource, project: 'posthog.json on another host', projectId: undefined }
}

function reasonFor(sources: Sources, host: Host): string {
    switch (sources.project) {
        case 'nothing':
            return `nothing sets a project in posthog.json or HOG_PROJECT_ID, so hog uses your latest login to ${host}`
        case 'posthog.json on another host':
            return `the project in posthog.json is on another host, so hog uses your latest login to ${host}`
    }

    if (sources.host === sources.project) {
        return `${sources.project} sets the host and the project`
    }

    const hostPart =
        sources.host === 'the latest login'
            ? 'the host is the one you last logged in to'
            : `${sources.host} sets the host`

    return `${sources.project} sets the project, and ${hostPart}`
}

export function chooseLogin(settings: HogSettings, query: LoginQuery): ChosenLogin {
    const host = query.host ?? query.configHost ?? fallbackHost(settings)
    const sources = sourcesFor(query, host)
    const { projectId } = sources

    const overridden = sources.host === '--host or HOG_HOST' || sources.project === 'HOG_PROJECT_ID'
    const choice: LoginChoice = {
        host: host ?? null,
        projectId: projectId ?? null,
        match: projectId === undefined ? 'fallback' : overridden ? 'override' : 'exact',
        reason: host === undefined ? 'hog has no login' : reasonFor(sources, host),
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
            `${namedBy} names project ${target.projectId}, but you aren't logged in to it on ${target.host}.${loggedIn}`,
            `Run \`${command}\` and pick project ${target.projectId} on the approval page. Each project has its own login.`,
            EXIT_USAGE,
            { configPath: query.configPath ?? null, host: target.host, projectId: target.projectId, command }
        )

        this.command = command
    }
}
