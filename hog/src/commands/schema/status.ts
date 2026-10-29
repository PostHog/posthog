import { defineCommand } from '@/core/command'
import { absolutePath } from '@/core/paths'
import { plural } from '@/core/text'

import { configRoot, fetchDefinitions, isLanguage, LANGUAGE_INFO } from './shared'

interface LanguageStatus {
    language: string
    file: string
    // `outdated` means the event definitions changed since the module was generated.
    status: 'up_to_date' | 'outdated' | 'missing' | 'unknown_language'
    eventCount: number | null
    updatedAt: string | null
}

export default defineCommand({
    description: 'Check whether the typed SDKs in posthog.json match your event definitions',
    scopes: ['event_definition:read'],
    notes: 'Compares the schema hash in posthog.json with the event definitions in PostHog now. Exits with code 1 when a module is missing or out of date, or posthog.json has no languages, so CI can catch a stale SDK.',
    examples: ['hog schema status'],

    async run({ ctx }) {
        const loaded = await ctx.config()
        const root = configRoot(ctx, loaded)
        const languages: LanguageStatus[] = []
        for (const [language, saved] of Object.entries(loaded?.config.languages ?? {})) {
            const file = absolutePath(root, saved.output_path)
            const base = {
                language,
                file: saved.output_path,
                eventCount: saved.event_count ?? null,
                updatedAt: saved.updated_at ?? null,
            }
            if (!isLanguage(language)) {
                languages.push({ ...base, status: 'unknown_language' })
                continue
            }
            if (!(await ctx.runtime.exists(file))) {
                languages.push({ ...base, status: 'missing' })
                continue
            }
            const definitions = await fetchDefinitions(ctx, language)
            languages.push({
                ...base,
                status: saved.schema_hash === definitions.schema_hash ? 'up_to_date' : 'outdated',
                eventCount: definitions.event_count,
            })
        }
        return { config: loaded?.path ?? null, languages }
    },

    human({ result, out }) {
        if (result.languages.length === 0) {
            out.line(out.style('No typed SDKs yet.', 'yellow', 'bold'))
            out.line(`Run ${out.style('hog schema pull --language typescript', 'bold')} to generate one.`)
            return
        }
        const labels = {
            up_to_date: 'up to date',
            outdated: 'out of date',
            missing: 'file missing',
            unknown_language: 'unknown language',
        }
        out.table(
            ['language', 'file', 'status', 'events', 'updated'],
            result.languages.map((entry) => [
                isLanguage(entry.language) ? LANGUAGE_INFO[entry.language].name : entry.language,
                entry.file,
                labels[entry.status],
                entry.eventCount,
                entry.updatedAt,
            ])
        )
        const stale = result.languages.filter((entry) => entry.status === 'outdated' || entry.status === 'missing')
        if (stale.length > 0) {
            out.line(`${plural(stale.length, 'module')} to update. Run ${out.style('hog schema pull', 'bold')}.`)
        }
    },

    agent({ result, out }) {
        out.jsonLines(result.languages)
    },

    exitCode: (result) =>
        result.languages.length > 0 && result.languages.every((entry) => entry.status === 'up_to_date') ? 0 : 1,

    telemetry: ({ result }) => ({
        languages: result.languages.map((entry) => (isLanguage(entry.language) ? entry.language : 'unknown')),
        statuses: result.languages.map((entry) => entry.status),
    }),
})
