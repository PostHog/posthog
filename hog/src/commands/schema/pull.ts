import { dirname } from 'node:path'

import { defineCommand } from '@/core/command'
import { SCHEMA_SDKS, updateConfig, type SchemaLanguage, type SchemaSdk } from '@/core/config'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { absolutePath, confinedWritePath, findGitRoot, isInside, storedPath } from '@/core/paths'
import { plural } from '@/core/text'

import {
    chosenFile,
    configRoot,
    fetchDefinitions,
    isLanguage,
    LANGUAGE_INFO,
    LANGUAGE_SDKS,
    LANGUAGES,
    moduleInfo,
    savedSdk,
    sdkLanguage,
    type Language,
} from './shared'

interface PulledLanguage {
    language: Language
    sdk: SchemaSdk | undefined
    file: string
    status: 'written' | 'would_write' | 'unchanged'
    eventCount: number
    schemaHash: string
}

export default defineCommand({
    description: 'Generate a typed PostHog SDK from your event definitions',
    writes: true,
    options: {
        language: {
            type: 'string',
            short: 'l',
            choices: LANGUAGES,
            description: 'The language to generate. Without it, hog regenerates every language in posthog.json',
        },
        sdk: {
            type: 'string',
            choices: SCHEMA_SDKS,
            description:
                'The SDK the module wraps, which posthog.json remembers. TypeScript: none generates only the event types, for posthog-react-native, posthog-node or any other SDK. Go: posthog-go for 1.x or posthog-go-v2 for 2.x. Without it, hog reads the posthog-go version from go.mod',
        },
        file: {
            type: 'string',
            placeholder: 'path',
            description: 'Where to write the module. posthog.json remembers it for the next run',
        },
        dryRun: {
            type: 'boolean',
            description: 'Fetch the event definitions and show what would change, without writing',
        },
    },
    scopes: ['event_definition:read'],
    notes: 'hog writes the module only when the event definitions changed or the file is missing, and records the language, path and schema hash in posthog.json. posthog-cli reads the same entries.',
    examples: [
        'hog schema pull --language typescript --file src/lib/',
        'hog schema pull',
        'hog schema pull -l python --file app/posthog_typed.py',
        'hog schema pull -l typescript --sdk none',
        'hog schema pull -l golang --sdk posthog-go-v2',
    ],

    async run({ options, ctx }) {
        const loaded = await ctx.config()
        const configured = loaded?.config.languages ?? {}
        const root = configRoot(ctx, loaded)

        let languages: Language[]
        if (options.language) {
            languages = [options.language]
        } else if (Object.keys(configured).length > 0) {
            languages = Object.keys(configured).filter(isLanguage)
        } else if (ctx.prompts) {
            languages = [
                await ctx.prompts.select(
                    'Which language should hog generate?',
                    LANGUAGES.map((value) => ({ value, label: LANGUAGE_INFO[value].name }))
                ),
            ]
        } else {
            throw new HogError(
                'language_required',
                'posthog.json has no languages yet, so hog needs to know which one to generate.',
                `Pass --language ${LANGUAGES.join(', --language ')}.`,
                EXIT_USAGE
            )
        }
        if (options.file !== undefined && languages.length !== 1) {
            throw new HogError(
                'usage_error',
                '--file names one module, but hog is generating several languages.',
                'Pass --language too.',
                EXIT_USAGE
            )
        }

        if (options.sdk !== undefined && !languages.includes(sdkLanguage(options.sdk))) {
            const language = sdkLanguage(options.sdk)
            const { name } = LANGUAGE_INFO[language]
            throw new HogError(
                'usage_error',
                `--sdk ${options.sdk} only applies to ${name}, but hog is not generating ${name}.`,
                `Pass --language ${language} too.`,
                EXIT_USAGE
            )
        }

        const repository = (await findGitRoot(ctx.runtime))?.root ?? root
        const pulled: PulledLanguage[] = []
        const entries: Partial<Record<Language, SchemaLanguage>> = {}
        for (const language of languages) {
            const saved = configured[language]
            const flag = options.sdk !== undefined && sdkLanguage(options.sdk) === language ? options.sdk : undefined
            // go.mod is searched from the module's folder.
            const folder =
                options.file !== undefined
                    ? absolutePath(ctx.runtime.cwd(), options.file)
                    : saved
                      ? dirname(absolutePath(root, saved.output_path))
                      : ctx.runtime.cwd()
            const { sdk, record } = await moduleSdk(ctx, language, flag, saved, folder)
            let file: string
            let target: string | undefined
            if (options.file !== undefined) {
                file = await chosenFile(ctx, options.file, language, sdk)
            } else if (saved) {
                file = absolutePath(root, saved.output_path)
                target = await confinedOutput(
                    ctx,
                    root,
                    file,
                    `posthog.json sets the ${moduleInfo(language, sdk).name} module path to ${saved.output_path}, which is outside the project, so hog won't write there.`,
                    'Change output_path in posthog.json to a path inside the project, or pass --file to choose where hog writes the module.'
                )
            } else {
                const info = moduleInfo(language, sdk)
                const answer = ctx.prompts
                    ? await ctx.prompts.text(`Where should hog write the ${info.name} module?`, {
                          initialValue: info.defaultFile,
                      })
                    : info.defaultFile
                file = await chosenFile(ctx, answer || info.defaultFile, language, sdk)
            }
            // The repository can plant a link at any path inside it, including one the person typed. A path the person
            // typed outside the repository is their own choice.
            if (target === undefined && isInside(repository, file)) {
                target = await confinedOutput(
                    ctx,
                    repository,
                    file,
                    `${storedPath(repository, file)} links to a file outside the repository, so hog won't write there.`,
                    'Remove the link, or pass --file with the path the link points to.'
                )
            }

            const definitions = await fetchDefinitions(ctx, language, sdk)
            const outputPath = storedPath(root, file)
            // The module carries the time PostHog generated it, so only the hash says whether the events changed.
            // PostHog hashes the 2.x module differently, so the hash also catches a go.mod change.
            const unchanged =
                saved?.output_path === outputPath &&
                recordedSdk(language, saved) === record &&
                saved.schema_hash === definitions.schema_hash &&
                (await ctx.runtime.exists(file))
            if (!unchanged && !options.dryRun) {
                await ctx.runtime.writeFile(target ?? file, definitions.content)
                entries[language] = {
                    output_path: outputPath,
                    sdk: record,
                    schema_hash: definitions.schema_hash,
                    updated_at: new Date(ctx.runtime.now()).toISOString(),
                    event_count: definitions.event_count,
                }
            }
            pulled.push({
                language,
                sdk,
                file: outputPath,
                status: unchanged ? 'unchanged' : options.dryRun ? 'would_write' : 'written',
                eventCount: definitions.event_count,
                schemaHash: definitions.schema_hash,
            })
        }

        const dryRun = options.dryRun === true
        if (Object.keys(entries).length === 0) {
            return { config: loaded?.path ?? null, configUpdated: false, dryRun, languages: pulled }
        }
        const config = await updateConfig(ctx.runtime, loaded, (raw) => {
            raw.languages = { ...(raw.languages as object | undefined), ...entries }
        })
        return { config: storedPath(ctx.runtime.cwd(), config), configUpdated: true, dryRun, languages: pulled }
    },

    human({ result, out }) {
        const labels = { unchanged: 'Up to date', would_write: 'Would generate', written: 'Generated' }
        const written = result.languages.filter((pulled) => pulled.status === 'written')
        const effects = result.languages.map(({ language, sdk, file, status, eventCount }) => {
            const label = out.style(labels[status], status === 'would_write' ? 'yellow' : 'green', 'bold')
            return `${label}  ${moduleInfo(language, sdk).name} in ${file} (${plural(eventCount, 'event')})`
        })
        if (result.configUpdated) {
            effects.push(`Saved the settings in ${result.config}`)
        }
        const notes = written.flatMap(({ language, sdk, file }, index) => {
            const { name, nextSteps } = moduleInfo(language, sdk)
            return [
                ...(index > 0 ? [''] : []),
                out.style(written.length > 1 ? `Next steps for ${name}:` : 'Next steps:', 'bold'),
                ...nextSteps(file).map((step, number) => `  ${number + 1}. ${step}`),
            ]
        })

        out.report({
            status: written.length > 0 ? 'done' : 'unchanged',
            result: result.dryRun
                ? 'Dry run: no files written'
                : written.length > 0
                  ? `Generated ${plural(written.length, 'typed SDK')}`
                  : `${plural(result.languages.length, 'typed SDK')} already up to date`,
            effects,
            notes,
        })
    },

    agent({ result, out }) {
        out.jsonLines(result.languages)
    },

    telemetry: ({ result }) => ({
        languages: result.languages.map((pulled) => pulled.language),
        sdks: result.languages.flatMap((pulled) => (pulled.sdk ? [pulled.sdk] : [])),
        written: result.languages.filter((pulled) => pulled.status === 'written').length,
    }),
})

async function confinedOutput(
    ctx: Context,
    root: string,
    file: string,
    problem: string,
    hint: string
): Promise<string> {
    const target = await confinedWritePath(ctx.runtime, root, file)
    if (target === undefined) {
        throw new HogError('unsafe_output_path', problem, hint)
    }

    return target
}

interface SdkChoice {
    sdk: SchemaSdk | undefined
    // What posthog.json keeps: a flag, a saved value or an answer, never what go.mod says.
    record: SchemaSdk | undefined
}

// Order: the flag, posthog.json, the project (go.mod), the prompt, the default.
async function moduleSdk(
    ctx: Context,
    language: Language,
    flag: SchemaSdk | undefined,
    saved: SchemaLanguage | undefined,
    folder: string
): Promise<SdkChoice> {
    const sdks = LANGUAGE_SDKS[language]
    if (!sdks) {
        return { sdk: undefined, record: undefined }
    }
    const chosen = flag ?? savedSdk(language, saved)
    if (chosen) {
        return { sdk: chosen, record: chosen }
    }
    const detected = await sdks.detect?.(ctx.runtime, folder)
    if (detected) {
        return { sdk: detected, record: undefined }
    }
    if (saved || !ctx.prompts || !sdks.prompt) {
        const sdk = sdks.choices[0]
        return { sdk, record: sdks.recordsDefault ? sdk : undefined }
    }
    const answer = await ctx.prompts.select(sdks.prompt.message, sdks.prompt.options)
    return { sdk: answer, record: answer }
}

// posthog-cli writes TypeScript entries without `sdk`, which means the default.
function recordedSdk(language: Language, saved: SchemaLanguage): SchemaSdk | undefined {
    const sdks = LANGUAGE_SDKS[language]
    return savedSdk(language, saved) ?? (sdks?.recordsDefault ? sdks.choices[0] : undefined)
}
