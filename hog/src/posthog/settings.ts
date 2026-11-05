import { z } from 'zod'

import { parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import { parseOrUndefined } from '@/core/schema'
import { StoreChoiceSchema } from '@/posthog/credential-store/types'

import { hostKey, HostSchema, type Host, type HostKey } from './host'
import { ProjectIdSchema } from './ids'

const LoginRecordBaseSchema = z.object({
    // hog probes the keychain only at login, because a probe can open a dialog. Each host keeps its
    // own answer, so a login over SSH that had to use the file doesn't hide a keychain login to
    // another host.
    store: StoreChoiceSchema,
    projectId: ProjectIdSchema,
    // The host the login was made for, with the path a self-hosted PostHog sits under. The login is
    // keyed by origin, so a posthog.json path on the same origin can't send it elsewhere.
    host: HostSchema,
    // Set on a file login that replaced a keychain login while the keychain was unusable, so the old
    // keychain item can still be there. Logout tries to remove it.
    keychainLeftover: z.literal(true).optional().catch(undefined),
})

// What settings.json keeps about the login to one host: everything except its secrets.
const LoginRecordSchema = z.discriminatedUnion('type', [
    LoginRecordBaseSchema.extend({ type: z.literal('personal_api_key') }),
    LoginRecordBaseSchema.extend({
        type: z.literal('oauth'),
        // Epoch milliseconds, for the access token.
        expiresAt: z.number(),
        scopes: z.array(z.string()),
        loginId: z.string(),
    }),
])

export type LoginRecord = z.output<typeof LoginRecordSchema>

// What `hog auth login` decided, kept so later runs don't decide again. Nothing in it is secret.
export interface HogSettings {
    logins?: Partial<Record<HostKey, LoginRecord>>
    // The host of the last login, which commands use when neither --host nor posthog.json names one.
    host?: Host
}

// Each part of the file is read on its own, so one entry hog doesn't recognize loses only itself.
const SettingsFileSchema = z.looseObject({
    logins: z.record(z.string(), z.unknown()).optional().catch(undefined),
    host: HostSchema.optional().catch(undefined),
})

const SETTINGS_FILE = 'settings.json'

function settingsPath(runtime: Runtime): string {
    return hogFile(runtime, SETTINGS_FILE)
}

// A record hog doesn't recognize, such as one a later version wrote, reads as no login. So does a
// record filed under another origin than its own host.
function parseLoginRecord(origin: string, value: unknown): LoginRecord | undefined {
    const record = parseOrUndefined(LoginRecordSchema, value)
    const key = parseOrUndefined(HostSchema, origin)
    return record && key && hostKey(record.host) === hostKey(key) ? record : undefined
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
    const raw = parseJsonOrUndefined(text, SettingsFileSchema) ?? {}
    const logins: Partial<Record<HostKey, LoginRecord>> = {}
    for (const [host, value] of Object.entries(raw.logins ?? {})) {
        const record = parseLoginRecord(host, value)
        if (record) {
            logins[hostKey(record.host)] = record
        }
    }
    return { logins, host: raw.host }
}

export function loginFor(settings: HogSettings, host: Host): LoginRecord | undefined {
    return settings.logins?.[hostKey(host)]
}

// The settings with the login for `host` replaced, or removed when `record` is undefined.
export function withLogin(settings: HogSettings, host: Host, record: LoginRecord | undefined): HogSettings {
    const key = hostKey(host)
    const { [key]: _previous, ...others } = settings.logins ?? {}
    return { ...settings, logins: record ? { ...others, [key]: record } : others }
}

export async function writeSettings(runtime: Runtime, settings: HogSettings): Promise<void> {
    await runtime.writePrivateFile(settingsPath(runtime), JSON.stringify(settings, null, 2))
}
