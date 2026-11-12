import { z } from 'zod'

import { parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import { itemName, type LoginTarget } from '@/posthog/credential-store/item-name'
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
    // Epoch milliseconds of the `hog auth login` that saved it. Renewals keep it. Without a project in
    // posthog.json or HOG_PROJECT_ID, commands use the host's login with the latest one.
    loggedInAt: z.number().optional(),
    // Set while the secret is still filed under the host alone, as hog filed it when it kept one login
    // per host. `readLogin` in `login/stored.ts` moves it to the login's own item.
    storedUnderHost: z.literal(true).optional(),
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

const StoredItemSchema = z.object({
    store: StoreChoiceSchema,
    host: HostSchema,
    projectId: ProjectIdSchema.nullable(),
})

export type StoredItem = z.output<typeof StoredItemSchema>

// What `hog auth login` decided, kept so later runs don't decide again. Nothing in it is secret.
export interface HogSettings {
    logins: LoginRecord[]
    // Secrets no login uses any more, which hog removes at the next login or logout. A login that
    // moves to another store or item leaves one behind when removing it failed or had to wait.
    pendingRemovals: StoredItem[]
    // The host of the last login, from before each login kept `loggedInAt`. Only `fallbackHost` reads it.
    host?: Host
}

// Each part of the file is read on its own, so one entry hog doesn't recognize loses only itself.
const SettingsFileSchema = z.looseObject({
    logins: z.record(z.string(), z.unknown()).optional().catch(undefined),
    pendingRemovals: z.array(z.unknown()).optional().catch(undefined),
    host: HostSchema.optional().catch(undefined),
})

const ProjectLoginsSchema = z.record(z.string(), z.unknown())

// The shape that kept one login per host marked a file login whose keychain item could still be there.
const OneLoginPerHostSchema = z.object({ keychainLeftover: z.boolean().optional() })

const SETTINGS_FILE = 'settings.json'

function settingsPath(runtime: Runtime): string {
    return hogFile(runtime, SETTINGS_FILE)
}

function sameTarget(record: LoginTarget, target: LoginTarget): boolean {
    return sameHost(record.host, target.host) && record.projectId === target.projectId
}

export function itemOf(record: LoginRecord): StoredItem {
    const { store, host } = record
    return { store, host, projectId: record.storedUnderHost ? null : record.projectId }
}

function sameItem(a: StoredItem, b: StoredItem): boolean {
    return a.store === b.store && itemName(a.host, a.projectId) === itemName(b.host, b.projectId)
}

// The copies hog left untracked when it kept one login per host: the file entry of a login that
// moved to the keychain, and the keychain item of a login that moved to the file.
function oneLoginPerHostLeftovers(record: LoginRecord, value: unknown): StoredItem[] {
    const { host } = record
    if (record.store === 'keychain') {
        return [{ store: 'file', host, projectId: null }]
    }

    return OneLoginPerHostSchema.safeParse(value).data?.keychainLeftover
        ? [{ store: 'keychain', host, projectId: null }]
        : []
}

// settings.json files each login under its origin, then its project. An origin can instead hold one
// record, the shape that kept a single login per host, whose secret is filed under the host alone.
// A record hog doesn't recognize, such as one a later version wrote, reads as no login. So does a
// record filed under another origin or project than its own.
function parseOrigin(origin: string, value: unknown): Pick<HogSettings, 'logins' | 'pendingRemovals'> {
    const key = HostSchema.safeParse(origin).data
    const single = LoginRecordSchema.safeParse(value).data
    if (key === undefined || (single && !sameHost(single.host, key))) {
        return { logins: [], pendingRemovals: [] }
    }

    if (single) {
        return {
            logins: [{ ...single, storedUnderHost: true }],
            pendingRemovals: oneLoginPerHostLeftovers(single, value),
        }
    }

    const logins = Object.entries(ProjectLoginsSchema.safeParse(value).data ?? {}).flatMap(([projectId, entry]) => {
        const record = LoginRecordSchema.safeParse(entry).data
        return record?.projectId === projectId && sameHost(record.host, key) ? [record] : []
    })

    return { logins, pendingRemovals: [] }
}

// A missing or broken file means hog has no settings yet. Any other read failure stops the command,
// because a later write would replace every login with an empty file.
export async function readSettings(runtime: Runtime): Promise<HogSettings> {
    let text: string
    try {
        text = await runtime.readFile(settingsPath(runtime))
    } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
            return { logins: [], pendingRemovals: [] }
        }
        throw error
    }

    const raw = parseJsonOrUndefined(text, SettingsFileSchema) ?? {}
    const settings: HogSettings = {
        logins: [],
        pendingRemovals: (raw.pendingRemovals ?? []).flatMap((item) => StoredItemSchema.safeParse(item).data ?? []),
        host: raw.host,
    }

    for (const [origin, value] of Object.entries(raw.logins ?? {})) {
        const parsed = parseOrigin(origin, value)
        settings.logins.push(...parsed.logins.filter((record) => !loginFor(settings, record)))
        settings.pendingRemovals.push(...parsed.pendingRemovals)
    }

    return settings
}

export function loginFor(settings: HogSettings, target: LoginTarget): LoginRecord | undefined {
    return settings.logins.find((record) => sameTarget(record, target))
}

export function loginsFor(settings: HogSettings, host: Host): LoginRecord[] {
    return settings.logins.filter((record) => sameHost(record.host, host))
}

function latest(records: readonly LoginRecord[]): LoginRecord | undefined {
    return records.reduce<LoginRecord | undefined>(
        (last, record) => (last === undefined || (record.loggedInAt ?? 0) > (last.loggedInAt ?? 0) ? record : last),
        undefined
    )
}

export function latestLoginFor(settings: HogSettings, host: Host): LoginRecord | undefined {
    return latest(loginsFor(settings, host))
}

// The host commands use when neither --host nor posthog.json names one: the host of the latest
// `hog auth login`. Logins saved before hog kept `loggedInAt` fall back to the host settings.json
// kept for the last login, while hog still has a login there.
export function fallbackHost(settings: HogSettings): Host | undefined {
    const last = latest(settings.logins)
    if (last?.loggedInAt !== undefined) {
        return last.host
    }

    const { host } = settings
    return host !== undefined && loginsFor(settings, host).length > 0 ? host : undefined
}

// The settings with the login for `target` replaced, or removed when `record` is undefined.
export function withLogin(settings: HogSettings, target: LoginTarget, record: LoginRecord | undefined): HogSettings {
    const others = settings.logins.filter((other) => !sameTarget(other, target))
    return { ...settings, logins: record ? [...others, record] : others }
}

// Resolves to the settings as written. A pending removal that a login uses, or that repeats another,
// is left out. `host` stays while a login there has no `loggedInAt`, because `fallbackHost` falls
// back to it once every login with `loggedInAt` is gone.
export async function writeSettings(runtime: Runtime, settings: HogSettings): Promise<HogSettings> {
    const inUse = settings.logins.map(itemOf)
    const pendingRemovals = settings.pendingRemovals.filter(
        (item, index, all) =>
            !inUse.some((used) => sameItem(used, item)) && all.findIndex((other) => sameItem(other, item)) === index
    )
    const { host: lastHost } = settings
    const keepsHost =
        lastHost !== undefined &&
        settings.logins.some((record) => record.loggedInAt === undefined && sameHost(record.host, lastHost))
    const host = keepsHost ? lastHost : undefined

    const logins: Record<string, Record<string, LoginRecord>> = {}
    for (const record of settings.logins) {
        const origin = hostKey(record.host)
        logins[origin] = { ...logins[origin], [record.projectId]: record }
    }

    const written: HogSettings = { logins: settings.logins, pendingRemovals, ...(host === undefined ? {} : { host }) }
    const file = { logins, ...(pendingRemovals.length > 0 ? { pendingRemovals } : {}), ...(host ? { host } : {}) }
    await runtime.writePrivateFile(settingsPath(runtime), JSON.stringify(file, null, 2))

    return written
}
