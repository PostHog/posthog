import type { PostHogApi } from '@/posthog/api'

import { createEndpoint, createInsightVariable, updateEndpoint } from './api'
import { compare, type Change } from './changes'
import type { LocalEndpoint } from './files'
import {
    apiVariableType,
    hogqlOf,
    remoteVariableNames,
    requestBody,
    variableReferences,
    type Endpoint,
    type EndpointFile,
    type InsightVariable,
    type ResolvedVariables,
} from './model'

export interface VariableChange {
    name: string
    change: 'add' | 'remove' | 'retype'
    type?: string
    from?: string
}

export interface PushItem {
    name: string
    path: string
    action: 'create' | 'update' | 'skip'
    reason?: string
    // PostHog would reject the file, so the push fails.
    invalid?: boolean
    changes: Change[]
    variables: VariableChange[]
    file: EndpointFile
}

function variableChanges(
    file: EndpointFile,
    remoteNames: string[],
    existing: Map<string, InsightVariable>
): VariableChange[] {
    const changes: VariableChange[] = []
    for (const variable of file.variables ?? []) {
        const known = existing.get(variable.name)
        if (!remoteNames.includes(variable.name)) {
            changes.push({ name: variable.name, change: 'add', type: variable.type })
        } else if (known && known.type !== apiVariableType(variable.type)) {
            changes.push({ name: variable.name, change: 'retype', type: variable.type, from: known.type })
        }
    }
    const localNames = new Set((file.variables ?? []).map((variable) => variable.name))
    for (const name of remoteNames.filter((remote) => !localNames.has(remote))) {
        changes.push({ name, change: 'remove' })
    }
    return changes
}

// Why PostHog would reject the file, checked before anything is sent.
function rejection(file: EndpointFile, remoteNames: string[]): string | undefined {
    const references = variableReferences(hogqlOf(file))
    const localNames = (file.variables ?? []).map((variable) => variable.name)
    const removedButUsed = remoteNames.filter((name) => !localNames.includes(name) && references.includes(name))
    if (removedButUsed.length > 0) {
        return `The query still uses removed variables: ${removedButUsed.join(', ')}`
    }
    const unused = localNames.filter((name) => !references.includes(name))
    if (unused.length > 0) {
        return `The query doesn't use these variables, so remove them from the file: ${unused.join(', ')}`
    }
    return undefined
}

export function planPush(locals: LocalEndpoint[], remotes: Endpoint[], variables: InsightVariable[]): PushItem[] {
    const remoteByName = new Map(remotes.map((endpoint) => [endpoint.name, endpoint]))
    const existing = new Map(variables.map((variable) => [variable.code_name, variable]))
    const seen = new Map<string, string>()
    return locals.map(({ path, file }): PushItem => {
        const remote = remoteByName.get(file.name)
        const remoteNames = remoteVariableNames(remote)
        const base = { name: file.name, path, file, changes: [], variables: [] }
        const duplicate = seen.get(file.name)
        if (duplicate) {
            return { ...base, action: 'skip', invalid: true, reason: `${duplicate} defines the same endpoint` }
        }
        seen.set(file.name, path)
        const reason = rejection(file, remoteNames)
        if (reason) {
            return { ...base, action: 'skip', invalid: true, reason }
        }
        const variableDiff = variableChanges(file, remoteNames, existing)
        if (!remote) {
            return { ...base, action: 'create', variables: variableDiff }
        }
        const changes = compare(file, remote)
        // PostHog keeps a variable's type when an endpoint changes, so a type change alone is nothing to push.
        const retyped = variableDiff.filter((change) => change.change === 'retype')
        if (changes.length === 0 && variableDiff.length === retyped.length) {
            const reason = retyped.length
                ? `No changes hog can push. Change the type of ${retyped.map((change) => change.name).join(', ')} in PostHog`
                : 'No changes'
            return { ...base, action: 'skip', reason, variables: retyped }
        }
        return { ...base, action: 'update', changes, variables: variableDiff }
    })
}

export interface PushOutcome {
    name: string
    path: string
    status: 'created' | 'updated' | 'failed'
    uiUrl?: string | null
    error?: string
}

// Creates the variables a file adds that the project doesn't have yet, then the endpoint. A
// failure stops only its own endpoint.
export async function applyPush(
    api: PostHogApi,
    items: PushItem[],
    variables: InsightVariable[]
): Promise<PushOutcome[]> {
    const known = new Map(variables.map((variable) => [variable.code_name, variable]))
    const outcomes: PushOutcome[] = []
    for (const item of items) {
        if (item.action === 'skip') {
            continue
        }
        try {
            const resolved: ResolvedVariables = new Map()
            for (const variable of item.file.variables ?? []) {
                let insightVariable = known.get(variable.name)
                if (!insightVariable) {
                    insightVariable = await createInsightVariable(api, {
                        code_name: variable.name,
                        type: apiVariableType(variable.type),
                        ...(variable.default !== undefined ? { default_value: variable.default } : {}),
                        // A single-selection list keeps only the first value of an array default.
                        ...(Array.isArray(variable.default) ? { is_multi: true } : {}),
                    })
                    known.set(variable.name, insightVariable)
                }
                resolved.set(variable.name, insightVariable)
            }
            const body = requestBody(item.file, resolved)
            const saved =
                item.action === 'create' ? await createEndpoint(api, body) : await updateEndpoint(api, item.name, body)
            outcomes.push({
                name: item.name,
                path: item.path,
                status: item.action === 'create' ? 'created' : 'updated',
                uiUrl: saved.ui_url,
            })
        } catch (error) {
            outcomes.push({
                name: item.name,
                path: item.path,
                status: 'failed',
                error: error instanceof Error ? error.message : String(error),
            })
        }
    }
    return outcomes
}

export interface PullItem {
    name: string
    path: string
    action: 'create' | 'update' | 'skip'
    reason?: string
    changes: Change[]
    endpoint: Endpoint
}

// An endpoint a local file already defines updates that file in place. Any other goes to
// `<folder>/<name>.yaml`, or to `file` when the target is a single YAML file.
export function planPull(remotes: Endpoint[], locals: LocalEndpoint[], pathFor: (name: string) => string): PullItem[] {
    const localByName = new Map(locals.map((local) => [local.file.name, local]))
    return remotes.map((endpoint): PullItem => {
        const local = localByName.get(endpoint.name)
        if (!local) {
            return { name: endpoint.name, path: pathFor(endpoint.name), action: 'create', changes: [], endpoint }
        }
        const changes = compare(local.file, endpoint)
        return changes.length === 0
            ? { name: endpoint.name, path: local.path, action: 'skip', reason: 'No changes', changes, endpoint }
            : { name: endpoint.name, path: local.path, action: 'update', changes, endpoint }
    })
}
