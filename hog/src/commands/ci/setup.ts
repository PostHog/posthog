import { CI_SETUP_COMMAND, policyRequestFlow, policyRequestWait, resolveSubject } from '@/ci/policy-request'
import {
    presetConditions,
    providerSettings,
    requiredPresets,
    type Preset,
    type ProviderSettings,
} from '@/ci/provider-settings'
import type { WorkloadConditions } from '@/ci/providers/registry'
import { detectRepositoryProvider, providerByKey, readRepository } from '@/ci/repository'
import { clearPending, printPending, resumeApproval, runApproval, type ApprovalResult } from '@/core/approval'
import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, type Output } from '@/core/output'
import type { Prompts } from '@/core/prompts'
import { cloudRegion, type Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'

interface Setup {
    provider: string
    // What to add to posthog.json. A job reads a host from it only for PostHog Cloud.
    posthogJson: { host?: Host; projectId: number }
    snippet: string
    // The job sets it as HOG_HOST when posthog.json can't name it.
    host: Host
    docsUrl: string
}

interface NeededPreset {
    option: string
    label: string
    help: string
    example: string
}

interface InputRequired {
    status: 'input_required'
    provider: string
    values: NeededPreset[]
    presets: NeededPreset[]
    docsUrl: string
}

type SetupResult =
    | (Extract<ApprovalResult<never>, { status: 'pending' }> & Setup)
    | ({ status: 'approved'; policyId: string } & Setup)
    | InputRequired

function setupFor(settings: ProviderSettings, target: { host: Host; projectId: ProjectId }): Setup {
    const cloud = cloudRegion(target.host)
    return {
        provider: settings.name,
        posthogJson: { ...(cloud ? { host: cloud } : {}), projectId: Number(target.projectId) },
        snippet: settings.setup_snippet,
        host: target.host,
        docsUrl: settings.docs_url,
    }
}

function scopesFrom(raw: readonly string[] | undefined): string[] {
    const scopes = (raw ?? []).flatMap((value) => value.split(',')).map((scope) => scope.trim())
    return [...new Set(scopes.filter(Boolean))].sort()
}

function usage(code: string, message: string, hint: string): HogError {
    return new HogError(code, message, hint, EXIT_USAGE)
}

// `--preset key=value`, or a bare `key` for a preset that takes no value.
function presetOptions(raw: readonly string[] | undefined): Map<string, string | undefined> {
    const given = new Map<string, string | undefined>()
    for (const entry of raw ?? []) {
        const separator = entry.indexOf('=')
        const key = separator === -1 ? entry : entry.slice(0, separator)
        if (!key) {
            throw usage(
                'invalid_preset',
                `--preset ${entry} has no name before the =.`,
                'Pass it like --preset name=value.'
            )
        }
        if (given.has(key)) {
            throw usage('invalid_preset', `--preset ${key} appears twice.`, 'Pass each preset once.')
        }
        given.set(key, separator === -1 ? undefined : entry.slice(separator + 1))
    }
    return given
}

function valueProblem(value: string): string | undefined {
    if (!value || value.trim() !== value) {
        return 'Enter a value without spaces around it.'
    }
    if (escapeControls(value) !== value) {
        return "The value can't contain control characters."
    }
    // Policies compare values exactly, so a pattern would never match what the person meant.
    return /[*?[\]]/.test(value) ? "The value can't contain *, ?, [ or ]." : undefined
}

function needed(preset: Preset): NeededPreset {
    const option = preset.takes_value ? `--preset ${preset.key}=<value>` : `--preset ${preset.key}`
    return { option, label: preset.label, help: preset.help_text, example: preset.placeholder }
}

// Which runs may get a token, from --preset, then from questions when a person can answer them.
// Without a person, the presets still needed come back with PostHog's explanations.
async function collectConditions(
    settings: ProviderSettings,
    raw: readonly string[] | undefined,
    prompts: Prompts | undefined
): Promise<{ status: 'ready'; conditions: WorkloadConditions } | InputRequired> {
    const given = presetOptions(raw)
    const byKey = new Map(settings.condition_presets.map((preset) => [preset.key, preset]))
    for (const key of given.keys()) {
        if (!byKey.has(key)) {
            throw usage(
                'unknown_preset',
                `${settings.name} has no preset named ${key}.`,
                `Pass one of: ${[...byKey.keys()].join(', ')}.`
            )
        }
    }
    const required = requiredPresets(settings)
    const chosen = [...new Set([...required, ...[...given.keys()].map((key) => byKey.get(key)!)])]
    const runPresets = settings.condition_presets.filter((preset) => !required.includes(preset))
    if (runPresets.length === 0) {
        // A policy without a run restriction would trust every run, so hog never asks for one.
        throw new HogError(
            'missing_conditions',
            `PostHog offers no preset that says which ${settings.name} runs may get a token.`,
            'Add the policy in PostHog under the project settings, Trusted workloads.'
        )
    }
    if (!chosen.some((preset) => runPresets.includes(preset)) && prompts) {
        const key = await prompts.select(
            'Which runs may get a token?',
            runPresets.map((preset) => ({
                value: preset.key,
                label: escapeControls(preset.label),
                hint: escapeControls(preset.help_text),
            }))
        )
        chosen.push(byKey.get(key)!)
    }
    const missing: NeededPreset[] = []
    const conditions: WorkloadConditions = {}
    for (const preset of chosen) {
        let value = given.get(preset.key) ?? ''
        if (preset.takes_value && !given.has(preset.key) && prompts) {
            value = await prompts.text(escapeControls(preset.label), {
                help: escapeControls(preset.help_text),
                initialValue: valueProblem(preset.default_value) ? undefined : preset.default_value,
                validate: valueProblem,
            })
        }
        if (preset.takes_value && !value) {
            missing.push(needed(preset))
            continue
        }
        const problem = preset.takes_value ? valueProblem(value) : undefined
        if (problem) {
            throw usage('invalid_preset', `--preset ${preset.key}: ${problem}`, preset.help_text)
        }
        for (const [claim, claimValue] of Object.entries(presetConditions(preset, value))) {
            // Conditions all have to hold, so a preset never quietly replaces what another one asked for.
            if (claim in conditions && conditions[claim] !== claimValue) {
                throw usage(
                    'conflicting_presets',
                    `Two presets ask for different values of ${claim}.`,
                    'Keep only one of them.'
                )
            }
            conditions[claim] = claimValue
        }
    }
    const choices = chosen.some((preset) => runPresets.includes(preset)) ? [] : runPresets.map(needed)
    if (missing.length || choices.length) {
        return {
            status: 'input_required',
            provider: settings.name,
            values: missing,
            presets: choices,
            docsUrl: settings.docs_url,
        }
    }
    return { status: 'ready', conditions }
}

function printInputRequired(out: Output, result: InputRequired): void {
    // PostHog wrote these, so they go through escapeControls like any server text shown in a terminal.
    const item = (entry: NeededPreset, example: boolean): void => {
        out.line('')
        out.line(`  ${escapeControls(entry.option)}  ${escapeControls(entry.label)}`)
        const help = example ? `${entry.help} For example, ${entry.example}.` : entry.help
        out.line(out.style(`      ${escapeControls(help)}`, 'dim'))
    }
    out.line(`hog needs a few more answers to set up ${escapeControls(result.provider)}. Pass them as options:`)
    result.values.forEach((entry) => item(entry, true))
    if (result.presets.length) {
        out.line('')
        out.line('And say which runs may get a token, with one of:')
        result.presets.forEach((entry) => item(entry, false))
    }
    out.line('')
    out.line(out.style(`More in ${escapeControls(result.docsUrl)}`, 'dim'))
}

function snippetNotes(out: Output, result: Setup): string[] {
    return [
        'Add this to posthog.json in the repository:',
        '',
        escapeControls(JSON.stringify(result.posthogJson, null, 4)),
        '',
        `Then add this to the ${escapeControls(result.provider)} job that runs hog:`,
        '',
        escapeControls(result.snippet),
        '',
        result.posthogJson.host
            ? `Or, instead of posthog.json, set HOG_HOST=${result.host} and HOG_PROJECT_ID=${result.posthogJson.projectId} in the job.`
            : `This PostHog isn't PostHog Cloud, so the job also needs HOG_HOST=${result.host}.`,
        out.style(`More in ${escapeControls(result.docsUrl)}`, 'dim'),
    ]
}

export default defineCommand({
    description: 'Let a CI job use hog without a stored key, by asking an admin to trust its repository',
    options: {
        provider: {
            type: 'string',
            placeholder: 'key',
            description: 'The CI provider, when hog can not tell from the repository',
        },
        repository: {
            type: 'string',
            placeholder: 'name',
            description: "The workload's name, like owner/repo, when it is not the origin remote",
        },
        subjectId: {
            type: 'string',
            placeholder: 'id',
            description: "The workload's immutable ID, like the repository ID, when PostHog can not look it up",
        },
        preset: {
            type: 'string',
            multiple: true,
            placeholder: 'name=value',
            description:
                'Which runs may get a token, like branch_push=main or environment=production. Without it, hog asks, or lists the presets the provider offers',
        },
        scope: {
            type: 'string',
            multiple: true,
            description:
                'The scopes the job gets, like error_tracking:write. Separate several with commas, as in --scope error_tracking:write,query:read, or repeat the flag',
        },
        wait: { type: 'boolean', description: 'Wait for the request an earlier run started to be approved' },
    },
    refusesCI: {
        reason: 'asks an admin to trust a CI job from your machine',
        hint: 'Run `hog ci setup` on your machine, in the repository the job builds.',
    },
    scopes: ['workload_trust_policy_request:write'],
    notes: [
        'Run it in the repository, logged in with `hog auth login`. hog asks PostHog to trust the repository in your project, and an organization admin approves the request in the browser.',
        'When you are an admin, hog opens the approval page and waits. Otherwise it names the admins and prints the link to send them.',
        'The job then exchanges its OIDC token for a short-lived PostHog token on each run, with the scopes you asked for.',
    ].join('\n'),
    examples: [
        'hog ci setup --scope error_tracking:write',
        'hog ci setup --preset branch_push=main --scope error_tracking:write',
        'hog ci setup --preset environment=production --scope endpoint:write,query:read',
        'hog ci setup --wait',
    ],

    async run({ options, ctx }): Promise<SetupResult> {
        if (options.wait) {
            const api = await ctx.posthog()
            const { host, projectId } = (await ctx.session()).current
            const { value: approved } = await resumeApproval(ctx, policyRequestWait(api, { host, projectId }))
            // The snippet needs the provider's settings, so the request stays for another --wait until they load.
            const settings = await providerSettings(api, approved.projectId, approved.provider)
            await clearPending(ctx.runtime, CI_SETUP_COMMAND)
            return { status: 'approved', policyId: approved.policyId, ...setupFor(settings, approved) }
        }

        // The checks that need no PostHog run first, so a usage mistake never waits on the keychain.
        const scopes = scopesFrom(options.scope)
        if (scopes.length === 0) {
            throw usage(
                'missing_scopes',
                'Say which scopes the job gets.',
                'Pass --scope with the scopes, like --scope error_tracking:write for source map uploads, or --scope endpoint:write,query:read for several.'
            )
        }
        const repository = await readRepository(ctx.runtime)
        const provider = options.provider
            ? providerByKey(options.provider)
            : await detectRepositoryProvider(ctx.runtime, repository)
        // The token carries the provider's exact spelling of the name, which a remote URL may not have.
        if (options.subjectId && !options.repository) {
            throw usage(
                'missing_repository',
                '--subject-id needs --repository with the exact name the provider shows, because PostHog matches both.',
                'Pass --repository too, like --repository PostHog/posthog.'
            )
        }
        const subjectName =
            options.repository ??
            (repository?.remote === undefined ? undefined : provider.nameFromRemote(repository.remote))
        if (!subjectName) {
            throw usage(
                'missing_repository',
                `hog couldn't read the ${provider.name} repository from the origin remote.`,
                'Pass --repository, like --repository owner/repo.'
            )
        }

        const api = await ctx.posthog()
        const { host, projectId } = (await ctx.session()).current
        const target = { host, projectId }
        const settings = await providerSettings(api, projectId, provider.key)
        const collected = await collectConditions(settings, options.preset, ctx.prompts)
        if (collected.status === 'input_required') {
            return collected
        }
        const { conditions } = collected
        const subject = options.subjectId
            ? { subject: options.subjectId, subject_name: subjectName }
            : await resolveSubject(api, projectId, settings, subjectName, conditions)
        const name = `${subject.subject_name} on ${provider.name}`

        const result = await runApproval(
            ctx,
            policyRequestFlow(api, target, { settings, name, subject, conditions, scopes })
        )
        const setup = setupFor(settings, target)
        if (result.status === 'pending') {
            return { ...result, ...setup }
        }
        await clearPending(ctx.runtime, CI_SETUP_COMMAND)
        return { status: 'approved', policyId: result.value.policyId, ...setup }
    },

    human({ result, out }) {
        if (result.status === 'input_required') {
            printInputRequired(out, result)
            return
        }
        if (result.status === 'pending') {
            printPending(out, result, 'policy request', ['', ...snippetNotes(out, result)])
            return
        }
        out.report({
            result: `${escapeControls(result.provider)} jobs can now use hog in this project`,
            notes: snippetNotes(out, result),
        })
    },

    agent({ result, out }) {
        out.json(result)
    },

    telemetry: ({ result }) => ({ status: result.status, provider: result.provider }),
})
