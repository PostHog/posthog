import { z } from 'zod'

import { hostKey, HostSchema, type Host } from '@/posthog/host'
import { ProjectIdSchema, type ProjectId } from '@/posthog/ids'

// What a stored login is for. hog keeps one login per host and project, because an OAuth token
// works in the one project the person picked when they approved it. A null `projectId` names a
// secret filed under its host alone, as hog filed it when it kept one login per host.
export interface LoginTarget<Project extends ProjectId | null = ProjectId> {
    host: Host
    projectId: Project
}

export type ItemName = string & z.$brand<'ItemName'>

// The project follows a "#", which a host can't contain, so a login's name never reads as a host.
export function itemName(host: Host, projectId: ProjectId | null): ItemName {
    return (projectId === null ? `${hostKey(host)}` : `${hostKey(host)}#${projectId}`) as ItemName
}

export function parseItemName(name: string): LoginTarget<ProjectId | null> | undefined {
    const separator = name.lastIndexOf('#')
    const host = HostSchema.safeParse(separator === -1 ? name : name.slice(0, separator)).data
    const projectId = separator === -1 ? null : ProjectIdSchema.safeParse(name.slice(separator + 1)).data

    return host && projectId !== undefined && itemName(host, projectId) === name ? { host, projectId } : undefined
}
