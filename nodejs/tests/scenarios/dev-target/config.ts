import { readFileSync, statSync } from 'fs'

export type DevConfig = {
    host: string
    offers: { teamId: number; token: string; workflowId: string }
    receiptsTeamId: number
    key: string
}

const NAMES = [
    'DEV_TARGET_HOST',
    'DEV_TARGET_OFFERS_TEAM_ID',
    'DEV_TARGET_OFFERS_TOKEN',
    'DEV_TARGET_WORKFLOW_ID',
    'DEV_TARGET_RECEIPTS_TEAM_ID',
    'DEV_TARGET_KEY_FILE',
] as const
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function devConfigOf(env: NodeJS.ProcessEnv): DevConfig {
    const missing = NAMES.filter((name) => !env[name])
    if (missing.length > 0) {
        throw new Error(`The dev target needs ${missing.join(', ')}, and it has no defaults for them.`)
    }
    const read = (name: (typeof NAMES)[number]): string => env[name]!
    const origin = (name: (typeof NAMES)[number]): string => {
        const url = new URL(read(name))
        if (url.protocol !== 'https:') {
            throw new Error(`${name} must be an https URL`)
        }
        return url.origin
    }
    const team = (name: (typeof NAMES)[number]): number => {
        const id = Number(read(name))
        if (!Number.isSafeInteger(id) || id <= 0) {
            throw new Error(`${name} must be a project id`)
        }
        return id
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
        host: origin('DEV_TARGET_HOST'),
        offers: { teamId: team('DEV_TARGET_OFFERS_TEAM_ID'), token, workflowId },
        receiptsTeamId: team('DEV_TARGET_RECEIPTS_TEAM_ID'),
        key,
    }
}
