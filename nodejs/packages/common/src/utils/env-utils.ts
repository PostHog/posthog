export enum NodeEnv {
    Development = 'dev',
    Production = 'prod',
    Test = 'test',
}

export function stringToBoolean(value: unknown, strict?: false): boolean
export function stringToBoolean(value: unknown, strict: true): boolean | null
export function stringToBoolean(value: unknown, strict = false): boolean | null {
    const stringValue = String(value).toLowerCase()
    const isStrictlyTrue = ['y', 'yes', 't', 'true', 'on', '1'].includes(stringValue)
    if (isStrictlyTrue) {
        return true
    }
    if (strict) {
        const isStrictlyFalse = ['n', 'no', 'f', 'false', 'off', '0'].includes(stringValue)
        return isStrictlyFalse ? false : null
    }
    return false
}

export function determineNodeEnv(): NodeEnv {
    let nodeEnvRaw = process.env.NODE_ENV
    if (nodeEnvRaw) {
        nodeEnvRaw = nodeEnvRaw.toLowerCase()
        if (nodeEnvRaw.startsWith(NodeEnv.Test)) {
            return NodeEnv.Test
        }
        if (nodeEnvRaw.startsWith(NodeEnv.Development)) {
            return NodeEnv.Development
        }
    }
    if (stringToBoolean(process.env.DEBUG)) {
        return NodeEnv.Development
    }
    return NodeEnv.Production
}

export const isTestEnv = (): boolean => determineNodeEnv() === NodeEnv.Test
export const isDevEnv = (): boolean => determineNodeEnv() === NodeEnv.Development
export const isProdEnv = (): boolean => determineNodeEnv() === NodeEnv.Production

// Keep this in sync with is_cloud() in posthog/cloud_utils.py.
// "dev" refers to the hosted development environment, not local development (which is "local").
export const isCloud = (): boolean =>
    ['EU', 'US', 'DEV', 'E2E'].includes((process.env.CLOUD_DEPLOYMENT ?? '').toUpperCase())

export function isOverflowBatchByDistinctId(): boolean {
    const overflowBatchByDistinctId = process.env.INGESTION_OVERFLOW_BATCH_BY_DISTINCT_ID
    return stringToBoolean(overflowBatchByDistinctId)
}

// Parse a comma-separated env var of team ids into a list, or '*' for "all teams".
export function parseTeamsList(teamsStr: string): number[] | '*' {
    // Trim so a whitespace-padded '*' (easy to produce in Helm/YAML) is still
    // recognized as the wildcard rather than silently parsing as an empty list.
    if (teamsStr.trim() === '*') {
        return '*'
    }
    return teamsStr
        .split(',')
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !isNaN(n))
}
