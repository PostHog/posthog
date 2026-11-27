import { readFileSync, statSync } from 'fs'

export type DevConfig = {
    host: string
    offers: { teamId: number; token: string; workflowId: string }
    receiptsTeamId: number
    monthlyRuns: number
    key: string
}

const NAMES = [
    'DEV_TARGET_OFFERS_TEAM_ID',
    'DEV_TARGET_OFFERS_TOKEN',
    'DEV_TARGET_WORKFLOW_ID',
    'DEV_TARGET_RECEIPTS_TEAM_ID',
    'DEV_TARGET_KEY_FILE',
    'DEV_TARGET_MONTHLY_RUNS',
] as const
// The only deployment a dev card sends to, so no setting can point its offers at production.
const DEV_HOST = 'https://app.dev.posthog.dev'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function devConfigOf(env: NodeJS.ProcessEnv): DevConfig {
    const missing = NAMES.filter((name) => !env[name])
    if (missing.length > 0) {
        throw new Error(`The dev target needs ${missing.join(', ')}, and it has no defaults for them.`)
    }
    const read = (name: (typeof NAMES)[number]): string => env[name]!
    const positive = (name: (typeof NAMES)[number], what: string): number => {
        const value = Number(read(name))
        if (!Number.isSafeInteger(value) || value <= 0) {
            throw new Error(`${name} must be ${what}`)
        }
        return value
    }
    const keyFile = read('DEV_TARGET_KEY_FILE')
    if ((statSync(keyFile).mode & 0o077) !== 0) {
        throw new Error(`DEV_TARGET_KEY_FILE must be readable by its owner only (mode 600)`)
    }
    const key = readFileSync(keyFile, 'utf8').trim()
    const token = read('DEV_TARGET_OFFERS_TOKEN').trim()
    const workflowId = read('DEV_TARGET_WORKFLOW_ID')
    if (!key || !token) {
        throw new Error(`${key ? 'DEV_TARGET_OFFERS_TOKEN' : 'DEV_TARGET_KEY_FILE'} holds no key`)
    }
    if (!UUID.test(workflowId)) {
        throw new Error('DEV_TARGET_WORKFLOW_ID must be a workflow id')
    }
    return {
        host: DEV_HOST,
        offers: { teamId: positive('DEV_TARGET_OFFERS_TEAM_ID', 'a project id'), token, workflowId },
        receiptsTeamId: positive('DEV_TARGET_RECEIPTS_TEAM_ID', 'a project id'),
        monthlyRuns: positive('DEV_TARGET_MONTHLY_RUNS', 'a count of workflow runs'),
        key,
    }
}
