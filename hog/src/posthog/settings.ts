import { z } from 'zod'

import { parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import { hostItemName, itemName, type ItemName, type LoginTarget } from '@/posthog/credential-store/item-name'
import { StoreChoiceSchema } from '@/posthog/credential-store/types'

import { hostKey, HostSchema, sameHost, type Host } from './host'
import { ProjectIdSchema } from './ids'

const LoginRecordBaseSchema = z.object({
    // hog probes the keychain only at login, because a probe can open a dialog. Each login keeps its
    // own answer, so a login over SSH that had to use the file doesn't hide a keychain login to
    // another host or project.
    store: StoreChoiceSchema,
    projectId: ProjectIdSchema,
    // The host the login was made for, with the path a self-hosted PostHog sits under. Logins are
    // keyed by origin, so a posthog.json path on the same origin can't send one elsewhere.
    host: HostSchema,
    // Set when a keychain item of an earlier login can still be there: a file login replaced a keychain
    // login while the keychain was unusable, or the keychain refused to remove the earlier item. Logout
    // tries to remove it.
    keychainLeftover: z.boolean().optional(),
    // Epoch milliseconds of the `hog auth login` that saved it. Renewals keep it. Without a project in
    // posthog.json or HOG_PROJECT_ID, commands use the host's login with the latest one.
    loggedInAt: z.number().optional(),
    // Set when the secret is filed under the host alone. See `hostItemName`.
    storedUnderHost: z.boolean().optional(),
})

// What settings.json keeps about one login: everything except its secrets.
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
    logins: LoginRecord[]
    // The host of the last login, which commands use when neither --host nor posthog.json names one.
    host?: Host
}

// Each part of the file is read on its own, so one entry hog doesn't recognize loses only itself.
const SettingsFileSchema = z.looseObject({
    logins: z.record(z.string(), z.unknown()).optional().catch(undefined),
    host: HostSchema.optional().catch(undefined),
})

const ProjectLoginsSchema = z.record(z.string(), z.unknown())

const SETTINGS_FILE = 'settings.json'

function settingsPath(runtime: Runtime): string {
    return hogFile(runtime, SETTINGS_FILE)
}

function sameTarget(record: LoginTarget, target: LoginTarget): boolean {
    return sameHost(record.host, target.host) && record.projectId === target.projectId
}

// settings.json files each login under its origin, then its project. An origin can instead hold one
// record, the shape that kept a single login per host, whose secret is filed under the host alone.
// A record hog doesn't recognize, such as one a later version wrote, reads as no login. So does a
// record filed under another origin or project than its own.
function parseOrigin(origin: string, value: unknown): LoginRecord[] {
    const key = HostSchema.safeParse(origin).data
    if (key === undefined) {
        return []
    }
    const fromKey = (record: LoginRecord | undefined): LoginRecord[] =>
        record && sameHost(record.host, key) ? [record] : []
    const single = LoginRecordSchema.safeParse(value).data
    if (single) {
        return fromKey({ ...single, storedUnderHost: true })
    }
    return Object.entries(ProjectLoginsSchema.safeParse(value).data ?? {}).flatMap(([projectId, entry]) => {
        const record = LoginRecordSchema.safeParse(entry).data
        return record?.projectId === projectId ? fromKey(record) : []
    })
}

// A missing or broken file means hog has no settings yet. Any other read failure stops the command,
// because a later write would replace every login with an empty file.
export async function readSettings(runtime: Runtime): Promise<HogSettings> {
    let text: string
    try {
        text = await runtime.readFile(settingsPath(runtime))
    } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
            return { logins: [] }
        }
        throw error
    }
    const raw = parseJsonOrUndefined(text, SettingsFileSchema) ?? {}
    const logins: LoginRecord[] = []
    for (const [origin, value] of Object.entries(raw.logins ?? {})) {
        for (const record of parseOrigin(origin, value)) {
            if (!logins.some((other) => sameTarget(other, record))) {
                logins.push(record)
            }
        }
    }
    return { logins, host: raw.host }
}

export function loginFor(settings: HogSettings, target: LoginTarget): LoginRecord | undefined {
    return settings.logins.find((record) => sameTarget(record, target))
}

export function loginsFor(settings: HogSettings, host: Host): LoginRecord[] {
    return settings.logins.filter((record) => sameHost(record.host, host))
}

// The login `hog auth login` saved last for the host. A record without `loggedInAt` counts as the oldest.
export function latestLoginFor(settings: HogSettings, host: Host): LoginRecord | undefined {
    return loginsFor(settings, host).reduce<LoginRecord | undefined>(
        (latest, record) =>
            latest === undefined || (record.loggedInAt ?? 0) > (latest.loggedInAt ?? 0) ? record : latest,
        undefined
    )
}

export function recordItemName(record: LoginRecord): ItemName {
    return record.storedUnderHost ? hostItemName(record.host) : itemName(record)
}

// The settings with the login for `target` replaced, or removed when `record` is undefined.
export function withLogin(settings: HogSettings, target: LoginTarget, record: LoginRecord | undefined): HogSettings {
    const others = settings.logins.filter((other) => !sameTarget(other, target))
    return { ...settings, logins: record ? [...others, record] : others }
}

export async function writeSettings(runtime: Runtime, settings: HogSettings): Promise<void> {
    const logins: Record<string, Record<string, LoginRecord>> = {}
    for (const record of settings.logins) {
        const origin = hostKey(record.host)
        logins[origin] = { ...logins[origin], [record.projectId]: record }
    }
    const file = settings.host === undefined ? { logins } : { logins, host: settings.host }
    await runtime.writePrivateFile(settingsPath(runtime), JSON.stringify(file, null, 2))
}
