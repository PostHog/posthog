import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import type { StoreChoice } from '@/posthog/credential-store/types'

import { hostKey, type HostKey } from './host'

// What settings.json keeps about the login to one host: everything except its secrets.
interface LoginRecordBase {
    // hog probes the keychain only at login, because a probe can open a dialog. Each host keeps its
    // own answer, so a login over SSH that had to use the file doesn't hide a keychain login to
    // another host.
    store: StoreChoice
    projectId: string
    // The host the login was made for, with the path a self-hosted PostHog sits under. The login is
    // keyed by origin, so a posthog.json path on the same origin can't send it elsewhere.
    host: string
    // Set on a file login that replaced a keychain login while the keychain was unusable, so the old
    // keychain item can still be there. Logout tries to remove it.
    keychainLeftover?: true
}

export type LoginRecord =
    | (LoginRecordBase & { type: 'personal_api_key' })
    // `expiresAt` is in epoch milliseconds, for the access token.
    | (LoginRecordBase & { type: 'oauth'; expiresAt: number; scopes: string[]; loginId: string })

// What `hog auth login` decided, kept so later runs don't decide again. Nothing in it is secret.
export interface HogSettings {
    logins?: Partial<Record<HostKey, LoginRecord>>
    // The host of the last login, which commands use when neither --host nor posthog.json names one.
    host?: string
}

const SETTINGS_FILE = 'settings.json'

function settingsPath(runtime: Runtime): string {
    return hogFile(runtime, SETTINGS_FILE)
}

// A record hog doesn't recognize, such as one a later version wrote, reads as no login.
function parseLoginRecord(origin: string, value: unknown): LoginRecord | undefined {
    const item = value as Record<string, unknown> | null
    if (
        (item?.store !== 'keychain' && item?.store !== 'file') ||
        typeof item.projectId !== 'string' ||
        typeof item.host !== 'string' ||
        hostKey(item.host) !== hostKey(origin)
    ) {
        return undefined
    }
    const { store, projectId, host } = item
    const base: LoginRecordBase =
        item.keychainLeftover === true ? { store, projectId, host, keychainLeftover: true } : { store, projectId, host }
    if (item.type === 'personal_api_key') {
        return { ...base, type: 'personal_api_key' }
    }
    if (
        item.type === 'oauth' &&
        typeof item.expiresAt === 'number' &&
        typeof item.loginId === 'string' &&
        Array.isArray(item.scopes) &&
        item.scopes.every((scope) => typeof scope === 'string')
    ) {
        const { expiresAt, loginId } = item
        return { ...base, type: 'oauth', expiresAt, scopes: item.scopes, loginId }
    }
    return undefined
}

// A missing or broken file means hog has no settings yet. Any other read failure stops the command,
// because a later write would replace the logins of every host with an empty file.
export async function readSettings(runtime: Runtime): Promise<HogSettings> {
    let text: string
    try {
        text = await runtime.readFile(settingsPath(runtime))
    } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
            return {}
        }
        throw error
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(text)
    } catch {
        return {}
    }
    const raw = (typeof parsed === 'object' && parsed !== null ? parsed : {}) as Record<string, unknown>
    const logins: Partial<Record<HostKey, LoginRecord>> = {}
    if (typeof raw.logins === 'object' && raw.logins !== null) {
        for (const [host, value] of Object.entries(raw.logins)) {
            const record = parseLoginRecord(host, value)
            if (record) {
                logins[hostKey(host)] = record
            }
        }
    }
    return {
        logins,
        host: typeof raw.host === 'string' ? raw.host : undefined,
    }
}

export function loginFor(settings: HogSettings, host: string): LoginRecord | undefined {
    return settings.logins?.[hostKey(host)]
}

// The settings with the login for `host` replaced, or removed when `record` is undefined.
export function withLogin(settings: HogSettings, host: string, record: LoginRecord | undefined): HogSettings {
    const { [hostKey(host)]: _previous, ...others } = settings.logins ?? {}
    return { ...settings, logins: record ? { ...others, [hostKey(host)]: record } : others }
}

export async function writeSettings(runtime: Runtime, settings: HogSettings): Promise<void> {
    await runtime.writePrivateFile(settingsPath(runtime), JSON.stringify(settings, null, 2))
}
