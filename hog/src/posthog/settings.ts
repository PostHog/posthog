import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import type { StoreChoice } from '@/posthog/credential-store/types'

import { hostKey, type HostKey } from './host'

// What settings.json keeps about the login to one host: everything except its secrets.
export interface LoginRecord {
    // hog probes the keychain only at login, because a probe can open a dialog. Each host keeps its
    // own answer, so a login over SSH that had to use the file doesn't hide a keychain login to
    // another host.
    store: StoreChoice
    type: 'personal_api_key'
    projectId: string
}

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
function parseLoginRecord(value: unknown): LoginRecord | undefined {
    const item = value as Record<string, unknown> | null
    if (
        (item?.store === 'keychain' || item?.store === 'file') &&
        item.type === 'personal_api_key' &&
        typeof item.projectId === 'string'
    ) {
        return { store: item.store, type: item.type, projectId: item.projectId }
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
            const record = parseLoginRecord(value)
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
