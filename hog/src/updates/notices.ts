import { z } from 'zod'

import type { Mode } from '@/core/agent'
import { parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime, RuntimeFetch } from '@/core/runtime'
import type { Telemetry } from '@/core/telemetry'

import {
    detectInstallMethod,
    INSTALL_KINDS,
    upgradeCommand,
    type InstallKind,
    type InstallMethod,
} from './install-method'
import { compareVersions, parseVersion } from './version'

const SHOWN_FILE = 'notices-shown.json'
const DAY_MS = 24 * 60 * 60 * 1000
export const MAX_NOTICE_LENGTH = 300

// Control characters can move the cursor or recolor a terminal, and bidirectional overrides can reorder
// the text a person reads, so a notice keeps neither.
const UNPRINTABLE = /[\u0000-\u001f\u007f-\u009f‎‏‪-‮⁦-⁩]/g

const NoticeText = z
    .string()
    .transform((text) => text.replace(UNPRINTABLE, ' ').replace(/\s+/g, ' ').trim())
    .pipe(z.string().min(1).max(MAX_NOTICE_LENGTH))

const NoticeVersion = z.string().refine((text) => parseVersion(text) !== undefined, { error: 'Not a semver version' })

// Only PostHog's own pages, so a notice can't send a person to another site.
const NoticeUrl = z.url({ protocol: /^https$/, hostname: /^(?:[a-z0-9-]+\.)*posthog\.com$/ })

export const NoticeSchema = z.object({
    id: z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/),
    level: z.enum(['info', 'warning']),
    message: NoticeText,
    url: NoticeUrl.optional(),
    // The hog versions the notice is for: `from` and up, and below `below`. Without either, every version.
    from: NoticeVersion.optional(),
    below: NoticeVersion.optional(),
    // The notice stops showing at this time.
    until: z.iso.datetime({ offset: true }).optional(),
    // Only for these install kinds. Without it, every install.
    installs: z.array(z.enum(INSTALL_KINDS)).min(1).optional(),
    // Adds the update command for this install, such as `brew upgrade hog`.
    upgrade: z.boolean().optional(),
})

export type Notice = z.infer<typeof NoticeSchema>

// A notice this hog can't read, such as one with a level a newer hog adds, is left out on its own, so it
// never hides the release or the other notices.
export const NoticeList = z
    .array(NoticeSchema.optional().catch(undefined))
    .catch([])
    .transform((notices) => notices.filter((notice): notice is Notice => notice !== undefined))

export type NoticeChannel = 'manifest' | 'api'

// The PostHog API adds it to its answers for the hog versions a notice names, so a hog with update
// checks off, such as one in CI, still gets the notice.
export const API_NOTICE_HEADER = 'X-PostHog-CLI-Notice'

export function noticesFromHeaders(headers: Headers): Notice[] {
    const value = headers.get(API_NOTICE_HEADER)
    return value ? (parseJsonOrUndefined(value, NoticeList) ?? []) : []
}

export interface HogInstall {
    version: string
    install: InstallKind | undefined
    now: number
}

export function appliesTo(notice: Notice, hog: HogInstall): boolean {
    if (notice.until !== undefined && hog.now >= Date.parse(notice.until)) {
        return false
    }
    if (notice.installs !== undefined && (hog.install === undefined || !notice.installs.includes(hog.install))) {
        return false
    }
    if (notice.from === undefined && notice.below === undefined) {
        return true
    }
    const running = parseVersion(hog.version)
    if (!running) {
        return false
    }
    const from = notice.from === undefined ? undefined : parseVersion(notice.from)
    const below = notice.below === undefined ? undefined : parseVersion(notice.below)
    return (!from || compareVersions(running, from) >= 0) && (!below || compareVersions(running, below) < 0)
}

const ShownSchema = z.record(z.string(), z.number())

async function readShown(runtime: Runtime): Promise<Record<string, number>> {
    try {
        return parseJsonOrUndefined(await runtime.readFile(hogFile(runtime, SHOWN_FILE)), ShownSchema) ?? {}
    } catch {
        return {}
    }
}

// The record only spaces out info notices, so a missing home folder or a failed write never fails the command.
async function saveShown(runtime: Runtime, shown: Record<string, number>): Promise<void> {
    const now = runtime.now()
    const recent = Object.fromEntries(Object.entries(shown).filter(([, at]) => now - at < DAY_MS))
    try {
        await runtime.writePrivateFile(hogFile(runtime, SHOWN_FILE), `${JSON.stringify(recent)}\n`)
    } catch {}
}

function updateHint(notice: Notice, method: InstallMethod | undefined): { text: string; command: string | null } {
    if (!notice.upgrade || !method) {
        return { text: '', command: null }
    }
    const command = upgradeCommand(method)
    if (command) {
        return { text: ` Run \`${command}\`.`, command }
    }
    return { text: method.kind === 'project' ? ' Update the hog dependency in package.json.' : '', command: null }
}

// GitHub Actions reads `::warning::` and `::notice::` lines from stderr too, and shows them on the run
// summary and the pull request. These escapes keep a line break or `%` in the text from ending the command.
function annotationData(text: string): string {
    return text.replaceAll('%', '%25').replaceAll('\r', '%0D').replaceAll('\n', '%0A')
}

export class Notices {
    private readonly pending = new Map<string, { notice: Notice; channel: NoticeChannel }>()

    constructor(private readonly runtime: Runtime) {}

    // A notice both channels send shows once, and telemetry credits the channel that named it first.
    add(channel: NoticeChannel, notices: readonly Notice[]): void {
        for (const notice of notices) {
            if (!this.pending.has(notice.id)) {
                this.pending.set(notice.id, { notice, channel })
            }
        }
    }

    // Collects the notices in every answer the wrapped fetch gets, from PostHog or not, because each one
    // goes through the same checks as a manifest notice.
    watch(fetchFn: RuntimeFetch): RuntimeFetch {
        return async (input, init) => {
            const response = await fetchFn(input, init)
            this.add('api', noticesFromHeaders(response.headers))
            return response
        }
    }

    // A warning shows on every command. An info notice shows at most once a day on a machine that keeps
    // hog's folder, and on every run of a CI job, which starts without one.
    async show(options: { mode: Mode; telemetry: Telemetry }): Promise<void> {
        if (this.pending.size === 0) {
            return
        }
        const { runtime } = this
        const now = runtime.now()
        const method = await detectInstallMethod(runtime).catch(() => undefined)
        const shown = await readShown(runtime)
        const hog = { version: runtime.build.version, install: method?.kind, now }
        const due = [...this.pending.values()].filter(
            ({ notice }) =>
                appliesTo(notice, hog) &&
                (notice.level === 'warning' || shown[notice.id] === undefined || now - shown[notice.id]! >= DAY_MS)
        )

        const annotate = runtime.env.GITHUB_ACTIONS === 'true' && options.mode.agent === undefined
        for (const { notice, channel } of due) {
            const hint = updateHint(notice, method)
            const text = `${notice.message}${hint.text}${notice.url ? ` ${notice.url}` : ''}`
            if (options.mode.format === 'json') {
                runtime.writeStderr(
                    `${JSON.stringify({
                        notice: {
                            id: notice.id,
                            level: notice.level,
                            message: notice.message,
                            url: notice.url ?? null,
                            command: hint.command,
                        },
                    })}\n`
                )
            } else if (!annotate) {
                runtime.writeStderr(`${notice.level === 'warning' ? 'Warning' : 'Notice'}: ${text}\n`)
            }
            if (annotate) {
                runtime.writeStderr(
                    `::${notice.level === 'warning' ? 'warning' : 'notice'} title=hog::${annotationData(text)}\n`
                )
            }
            options.telemetry.capture('cli notice shown', {
                notice_id: notice.id,
                notice_level: notice.level,
                notice_channel: channel,
                annotated: annotate,
            })
            if (notice.level === 'info') {
                shown[notice.id] = now
            }
        }

        if (due.some(({ notice }) => notice.level === 'info')) {
            await saveShown(runtime, shown)
        }
    }
}
