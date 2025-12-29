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

export const isCloud = (): boolean => !!process.env.CLOUD_DEPLOYMENT

export function isOverflowBatchByDistinctId(): boolean {
    const overflowBatchByDistinctId = process.env.INGESTION_OVERFLOW_BATCH_BY_DISTINCT_ID
    return stringToBoolean(overflowBatchByDistinctId)
}
