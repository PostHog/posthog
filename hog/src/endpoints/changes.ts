import {
    isPlainHogql,
    remoteVariableNames,
    remoteVariableValues,
    scheduleFor,
    withoutNulls,
    type Endpoint,
    type EndpointFile,
} from './model'

export type ChangeField = 'description' | 'query' | 'materialization' | 'schedule' | 'variables' | 'defaults'

// One field that differs between a local file and PostHog. Push reads it from remote to local,
// pull from local to remote.
export interface Change {
    field: ChangeField
    local: string
    remote: string
}

function sortKeys(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.keys(value)
                .sort()
                .map((key) => [key, sortKeys((value as Record<string, unknown>)[key])])
        )
    }
    return value
}

// PostHog stores variables inside the query, under IDs a file never names, so they're compared on their own.
function comparableQuery(query: Record<string, unknown>): string {
    if (isPlainHogql(query) && typeof query.query === 'string') {
        return query.query.replace(/\r\n?/g, '\n')
    }
    const { variables: _variables, ...rest } = query
    return JSON.stringify(sortKeys(withoutNulls(rest)), null, 2)
}

export function localQuery(file: EndpointFile): string {
    return file.query?.replace(/\r\n?/g, '\n') ?? comparableQuery(file.query_definition ?? {})
}

export function remoteQuery(endpoint: Endpoint): string {
    return comparableQuery(endpoint.query)
}

const sameSet = (a: string[], b: string[]): boolean =>
    a.length === b.length && [...a].sort().every((value, index) => value === [...b].sort()[index])

export function compare(file: EndpointFile, endpoint: Endpoint): Change[] {
    const changes: Change[] = []
    const add = (field: ChangeField, local: string, remote: string): void => {
        if (local !== remote) {
            changes.push({ field, local, remote })
        }
    }
    add('description', file.description ?? '', endpoint.description ?? '')
    add('query', localQuery(file), remoteQuery(endpoint))
    add(
        'materialization',
        file.materialization?.enabled ? 'enabled' : 'disabled',
        endpoint.is_materialized ? 'enabled' : 'disabled'
    )
    // PostHog keeps the refresh interval after materialization is turned off, so it only counts while on.
    const remoteSchedule = endpoint.is_materialized ? scheduleFor(endpoint.data_freshness_seconds) : undefined
    const localSchedule = file.materialization?.enabled ? file.materialization.schedule : undefined
    // A push without a schedule keeps the one PostHog has, so a file that names none matches any.
    if (localSchedule !== undefined) {
        add('schedule', localSchedule, remoteSchedule ?? '')
    }
    const localVariables = (file.variables ?? []).map((variable) => variable.name)
    const remoteVariables = remoteVariableNames(endpoint)
    if (!sameSet(localVariables, remoteVariables)) {
        changes.push({ field: 'variables', local: localVariables.join(', '), remote: remoteVariables.join(', ') })
    }
    // A variable without a default in the file takes the project's, so only the defaults a file sets count.
    const remoteValues = remoteVariableValues(endpoint)
    const show = (value: unknown): string => JSON.stringify(sortKeys(value ?? null))
    const changedDefaults = (file.variables ?? []).filter(
        (variable) =>
            variable.default !== undefined &&
            remoteValues.has(variable.name) &&
            show(variable.default) !== show(remoteValues.get(variable.name))
    )
    if (changedDefaults.length > 0) {
        changes.push({
            field: 'defaults',
            local: changedDefaults.map((variable) => `${variable.name}=${show(variable.default)}`).join(', '),
            remote: changedDefaults
                .map((variable) => `${variable.name}=${show(remoteValues.get(variable.name))}`)
                .join(', '),
        })
    }
    return changes
}
