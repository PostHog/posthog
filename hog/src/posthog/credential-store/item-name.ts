import { z } from 'zod'

import { hostKey, HostSchema, type Host } from '@/posthog/host'
import { ProjectIdSchema, type ProjectId } from '@/posthog/ids'

// What a stored login is for. hog keeps one login per host and project, because an OAuth token
// works in the one project the person picked when they approved it.
export interface LoginTarget {
    host: Host
    projectId: ProjectId
}

// The name a credential store files a secret under. Only `itemName` and `hostItemName` make one.
export type ItemName = string & z.$brand<'ItemName'>

// The project follows a "#", which a host can't contain, so a login's name never reads as a host.
export function itemName(target: LoginTarget): ItemName {
    return `${hostKey(target.host)}#${target.projectId}` as ItemName
}

// The name of a secret filed under its host alone. settings.json marks the login it belongs to with
// `storedUnderHost`, and the next write of that login files the secret under `itemName` instead.
export function hostItemName(host: Host): ItemName {
    return `${hostKey(host)}` as ItemName
}

// What a name in a store says. A null `projectId` is a secret filed under its host alone.
export interface ItemOwner {
    host: Host
    projectId: ProjectId | null
}

export function parseItemName(name: string): ItemOwner | undefined {
    const separator = name.lastIndexOf('#')
    if (separator === -1) {
        const host = HostSchema.safeParse(name).data
        return host && hostKey(host) === name ? { host, projectId: null } : undefined
    }
    const host = HostSchema.safeParse(name.slice(0, separator)).data
    const projectId = ProjectIdSchema.safeParse(name.slice(separator + 1)).data
    return host && projectId && itemName({ host, projectId }) === name ? { host, projectId } : undefined
}
