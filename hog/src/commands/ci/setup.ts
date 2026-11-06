import {
    CI_SETUP_COMMAND,
    policyRequestFlow,
    policyRequestWait,
    resolveSubject,
    type PolicyRequestInput,
} from '@/ci/policy-request'
import { CUSTOM_OIDC } from '@/ci/providers/custom/custom'
import { WORKLOAD_PROVIDERS, type WorkloadConditions, type WorkloadProvider } from '@/ci/providers/registry'
import { detectRepositoryProvider, pickProviderHint, readRepository } from '@/ci/repository'
import { clearPending, printPending, resumeApproval, runApproval, type ApprovalResult } from '@/core/approval'
import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, type Output } from '@/core/output'
import { kebabCase } from '@/core/text'
import type { PostHogApi } from '@/posthog/api'
import { cloudRegion, type Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'

interface Setup {
    provider: string
    // What to add to posthog.json. A job reads a host from it only for PostHog Cloud.
    posthogJson: { host?: Host; projectId: number }
    snippet: string
    // What the job sets instead of posthog.json, or as well as it for a self-hosted PostHog.
    env: { HOG_HOST: Host; HOG_PROJECT_ID: string }
    docsUrl: string
}

type SetupResult =
    | (Extract<ApprovalResult<never>, { status: 'pending' }> & Setup)
    | ({ status: 'approved'; policyId: string } & Setup)

function providerByKey(key: string): WorkloadProvider {
    const provider = WORKLOAD_PROVIDERS.find((candidate) => candidate.key === key)
    if (!provider) {
        throw new HogError(
            'unknown_provider',
            `hog doesn't support the CI provider ${key}.`,
            pickProviderHint(),
            EXIT_USAGE
        )
    }
    return provider
}

function setupFor(provider: WorkloadProvider, target: { host: Host; projectId: ProjectId }): Setup {
    const cloud = cloudRegion(target.host)
    return {
        provider: provider.name,
        posthogJson: { ...(cloud ? { host: cloud } : {}), projectId: Number(target.projectId) },
        snippet: provider.snippet(target),
        env: { HOG_HOST: target.host, HOG_PROJECT_ID: String(target.projectId) },
        docsUrl: provider.docsUrl,
    }
}

function scopesFrom(raw: readonly string[] | undefined): string[] {
    const scopes = (raw ?? []).flatMap((value) => value.split(',')).map((scope) => scope.trim())
    return [...new Set(scopes.filter(Boolean))].sort()
}

// `--condition claim=value`, repeatable.
function conditionPairs(raw: readonly string[]): WorkloadConditions {
    return Object.fromEntries(
        raw.map((entry) => {
            const separator = entry.indexOf('=')
            if (separator < 1 || separator === entry.length - 1) {
                throw new HogError(
                    'invalid_condition',
                    `--condition ${entry} isn't claim=value.`,
                    'Pass it like --condition environment=production.',
                    EXIT_USAGE
                )
            }
            return [entry.slice(0, separator), entry.slice(separator + 1)]
        })
    )
}

function extraConditions(provider: WorkloadProvider, raw: readonly string[]): WorkloadConditions {
    const given = conditionPairs(raw)
    for (const required of provider.requiredConditions ?? []) {
        const value = given[required.claim] ?? required.defaultValue
        if (!value) {
            throw new HogError(
                'missing_condition',
                `${provider.name} policies must set the ${required.label}.`,
                `Pass --condition ${required.claim}=<${required.label}>.`,
                EXIT_USAGE
            )
        }
        given[required.claim] = value
    }
    return given
}

function conditionsFrom(
    provider: WorkloadProvider,
    options: { branch?: string; environment?: string; condition?: string[] }
): WorkloadConditions {
    if (options.environment !== undefined && provider.environmentConditions === undefined) {
        throw new HogError(
            'environment_not_supported',
            `${provider.name} doesn't name an environment in its OIDC token.`,
            'Pass --branch instead.',
            EXIT_USAGE
        )
    }
    if (options.branch === undefined && options.environment === undefined) {
        throw new HogError(
            'missing_conditions',
            'Say which runs may get a token, so the policy never trusts every run of the repository.',
            'Pass --branch main, --environment production, or both.',
            EXIT_USAGE
        )
    }
    const extra = extraConditions(provider, options.condition ?? [])
    const runs: WorkloadConditions = {
        ...(options.branch === undefined ? {} : provider.branchConditions(options.branch)),
        ...(options.environment === undefined ? {} : provider.environmentConditions?.(options.environment)),
    }
    const clash = Object.keys(runs).find((claim) => claim in extra && extra[claim] !== runs[claim])
    if (clash !== undefined) {
        throw new HogError(
            'conflicting_condition',
            `--condition ${clash}=${extra[clash]} asks for a different ${clash} than --branch or --environment set.`,
            `Leave out --condition ${clash}.`,
            EXIT_USAGE
        )
    }
    return { ...extra, ...runs }
}

// Flags that only make sense for one kind of provider, so passing them to the other is a mistake, not a no-op.
const CUSTOM_FLAGS = ['issuer', 'subjectClaim', 'subject'] as const
const REGISTRY_FLAGS = ['branch', 'environment', 'repository', 'subjectId'] as const

function rejectFlags(
    options: Partial<Record<string, unknown>>,
    flags: readonly string[],
    code: string,
    rule: string,
    hint: string
): void {
    const passed = flags.find((flag) => options[flag] !== undefined)
    if (passed) {
        throw new HogError(code, `--${kebabCase(passed)} ${rule}`, hint, EXIT_USAGE)
    }
}

function issuerHost(issuer: string): string {
    const url = URL.parse(issuer)
    if (url?.protocol !== 'https:') {
        throw new HogError(
            'invalid_issuer',
            `--issuer ${issuer} isn't an https:// URL.`,
            'Pass the issuer exactly as its tokens carry it in iss, like --issuer https://auth.example.com.',
            EXIT_USAGE
        )
    }
    return url.host
}

interface CustomOptions {
    issuer?: string
    subjectClaim?: string
    subject?: string
    condition?: string[]
    name?: string
}

// A custom OIDC provider has no repository to read and no lookup, so every value comes from a flag.
function customRequest(options: CustomOptions, scopes: string[]): PolicyRequestInput {
    const missing = (flag: string, example: string): HogError =>
        new HogError(
            'missing_custom_option',
            `--provider custom needs ${flag}.`,
            `Pass it like ${example}.`,
            EXIT_USAGE
        )
    if (!options.issuer) {
        throw missing('--issuer', '--issuer https://auth.example.com')
    }
    const host = issuerHost(options.issuer)
    if (!options.subject) {
        throw missing('--subject', '--subject deploy-bot')
    }
    const conditions = conditionPairs(options.condition ?? [])
    if (Object.keys(conditions).length === 0) {
        throw new HogError(
            'missing_conditions',
            'Say which tokens may get a PostHog token, so the policy never trusts every token the issuer signs for the subject.',
            'Pass --condition with a claim the issuer sets, like --condition environment=production.',
            EXIT_USAGE
        )
    }
    return {
        provider: CUSTOM_OIDC,
        issuer: options.issuer,
        subjectClaim: options.subjectClaim ?? 'sub',
        name: options.name ?? `${options.subject} on ${host}`,
        subject: { subject: options.subject, subject_name: options.name ?? options.subject },
        conditions,
        scopes,
    }
}

async function requestPolicy(
    ctx: Context,
    api: PostHogApi,
    target: { host: Host; projectId: ProjectId },
    input: PolicyRequestInput
): Promise<SetupResult> {
    const result = await runApproval(ctx, policyRequestFlow(api, target, input))
    const setup = setupFor(input.provider, target)
    if (result.status === 'pending') {
        return { ...result, ...setup }
    }
    await clearPending(ctx.runtime, CI_SETUP_COMMAND)
    return { status: 'approved', policyId: result.value.policyId, ...setup }
}

function printSnippet(out: Output, result: Setup): void {
    out.line('')
    out.line('Add this to posthog.json in the repository:')
    out.line('')
    out.line(escapeControls(JSON.stringify(result.posthogJson, null, 4)))
    out.line('')
    out.line(`Then add this to the ${result.provider} job that runs hog:`)
    out.line('')
    out.line(escapeControls(result.snippet))
    out.line('')
    out.line(
        result.posthogJson.host
            ? `Or, instead of posthog.json, set HOG_HOST=${result.env.HOG_HOST} and HOG_PROJECT_ID=${result.env.HOG_PROJECT_ID} in the job.`
            : `This PostHog isn't PostHog Cloud, so the job also needs HOG_HOST=${result.env.HOG_HOST}.`
    )
    out.line(out.style(`More in ${result.docsUrl}`, 'dim'))
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
        branch: { type: 'string', description: 'Trust only runs for pushes to this branch, like main' },
        environment: {
            type: 'string',
            description: 'Trust only jobs that deploy to this environment, like production',
        },
        condition: {
            type: 'string',
            multiple: true,
            placeholder: 'claim=value',
            description:
                'A claim the token must carry with this exact value, like org_id=abcd1234 for Depot CI. Repeat for more. --provider custom needs at least one',
        },
        scope: {
            type: 'string',
            multiple: true,
            description:
                'The scopes the job gets, like error_tracking:write. Separate several with commas, as in --scope error_tracking:write,query:read, or repeat the flag',
        },
        issuer: {
            type: 'string',
            placeholder: 'url',
            description: 'With --provider custom: the OIDC issuer URL, exactly as its tokens carry it',
        },
        subjectClaim: {
            type: 'string',
            placeholder: 'claim',
            description: 'With --provider custom: the claim that names the workload. Defaults to sub',
        },
        subject: {
            type: 'string',
            placeholder: 'value',
            description: 'With --provider custom: the exact value the subject claim must have',
        },
        name: { type: 'string', description: 'What to call the policy in PostHog' },
        wait: { type: 'boolean', description: 'Wait for the request an earlier run started to be approved' },
    },
    scopes: ['workload_trust_policy_request:write'],
    notes: [
        'Run it in the repository, logged in with `hog auth login`. hog asks PostHog to trust the repository in your project, and an organization admin approves the request in the browser.',
        'When you are an admin, hog opens the approval page and waits. Otherwise it names the admins and prints the link to send them.',
        'The job then exchanges its OIDC token for a short-lived PostHog token on each run, with the scopes you asked for.',
    ].join('\n'),
    examples: [
        'hog ci setup --branch main --scope error_tracking:write',
        'hog ci setup --environment production --scope endpoint:write,query:read',
        'hog ci setup --provider custom --issuer https://auth.example.com --subject deploy-bot --condition env=production --scope error_tracking:write',
        'hog ci setup --wait',
    ],

    async run({ options, ctx }): Promise<SetupResult> {
        if (options.wait) {
            const api = await ctx.posthog()
            const { host, projectId } = (await ctx.session()).current
            const approved = await resumeApproval(ctx, policyRequestWait(api, { host, projectId }))
            await clearPending(ctx.runtime, CI_SETUP_COMMAND)
            return {
                status: 'approved',
                policyId: approved.policyId,
                ...setupFor(providerByKey(approved.provider), approved),
            }
        }

        // The checks that need no PostHog run first, so a usage mistake never waits on the keychain.
        const scopes = scopesFrom(options.scope)
        if (scopes.length === 0) {
            throw new HogError(
                'missing_scopes',
                'Say which scopes the job gets.',
                'Pass --scope with the scopes, like --scope error_tracking:write for source map uploads, or --scope endpoint:write,query:read for several.',
                EXIT_USAGE
            )
        }
        if (options.provider === CUSTOM_OIDC.key) {
            rejectFlags(
                options,
                REGISTRY_FLAGS,
                'option_not_for_custom_provider',
                "doesn't work with --provider custom.",
                'Pass --subject for the workload and --condition claim=value for each claim to check.'
            )
            const input = customRequest(options, scopes)
            const api = await ctx.posthog()
            const { host, projectId } = (await ctx.session()).current
            return await requestPolicy(ctx, api, { host, projectId }, input)
        }
        rejectFlags(
            options,
            CUSTOM_FLAGS,
            'custom_option_without_custom_provider',
            'only works with --provider custom.',
            'Pass --provider custom, or leave the flag out.'
        )
        const repository = await readRepository(ctx.runtime)
        const provider = options.provider
            ? providerByKey(options.provider)
            : await detectRepositoryProvider(ctx.runtime, repository)
        const conditions = conditionsFrom(provider, options)
        // The token carries the provider's exact spelling of the name, which a remote URL may not have.
        if (options.subjectId && !options.repository) {
            throw new HogError(
                'missing_repository',
                '--subject-id needs --repository with the exact name the provider shows, because PostHog matches both.',
                'Pass --repository too, like --repository PostHog/posthog.',
                EXIT_USAGE
            )
        }
        const subjectName =
            options.repository ??
            (repository?.remote === undefined ? undefined : provider.nameFromRemote(repository.remote))
        if (!subjectName) {
            throw new HogError(
                'missing_repository',
                `hog couldn't read the ${provider.name} repository from the origin remote.`,
                'Pass --repository, like --repository owner/repo.',
                EXIT_USAGE
            )
        }

        const api = await ctx.posthog()
        const { host, projectId } = (await ctx.session()).current
        const target = { host, projectId }
        if (!options.subjectId && provider.canLookUpSubject?.(conditions) === false) {
            throw new HogError(
                'missing_subject_id',
                `PostHog can't look up the repository ID for these ${provider.name} conditions.`,
                'Pass --subject-id with the repository ID, and --repository with its name.',
                EXIT_USAGE
            )
        }
        const subject = options.subjectId
            ? { subject: options.subjectId, subject_name: subjectName }
            : await resolveSubject(api, projectId, provider, subjectName)
        const name = options.name ?? `${subject.subject_name} on ${provider.name}`

        return await requestPolicy(ctx, api, target, {
            provider,
            issuer: provider.issuer,
            name,
            subject,
            conditions,
            scopes,
        })
    },

    human({ result, out }) {
        if (result.status === 'approved') {
            out.line(
                `${out.style('Approved.', 'green', 'bold')} ${result.provider} jobs can now use hog in this project.`
            )
        } else {
            printPending(out, result)
        }
        printSnippet(out, result)
    },

    agent({ result, out }) {
        out.json(result)
    },

    telemetry: ({ result }) => ({ status: result.status, provider: result.provider }),
})
