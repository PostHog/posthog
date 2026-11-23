import { z } from 'zod'

import type { StackDescription } from '@posthog/sdk/stack'

import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { ApiError, type PostHogApi } from '@/posthog/api'
import type { ProjectId } from '@/posthog/ids'
import { findNamed, getPage, type Page } from '@/posthog/pagination'
import { isScopeName } from '@/posthog/scope-challenge'

import type { ResolvedStack } from './config'
import { internalWords, movedError, stackApiFailure, stackGuidance } from './errors'
import { Description } from './evaluation'

const DiffId = z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$/, 'Use the ID from hog diff.')
export const parseDiffId = (raw: string, failure: ParseFailure): string => parseOrThrow(DiffId, raw, failure)
export const waitOption = {
    type: 'string',
    placeholder: 'id',
    description: 'Wait for an existing diff or push to finish',
    parse: parseDiffId,
} as const

export const actions = ['create', 'update', 'recreate', 'remove', 'adopt', 'rename', 'release'] as const
const Action = z.enum(actions)
const Source = z.object({ repository: z.string().max(500), branch: z.string().max(500), commit: z.string().max(100) })
const StartRequest = z.object({ description: Description, source: Source })
const PushRequest = z.object({ max_removals: z.int().nonnegative().optional() })
const Location = z.object({ file: z.string(), export: z.string().optional() })

function serviceText(fallback: string): z.ZodPipe<z.ZodString, z.ZodTransform<string, string>> {
    return z.string().transform((text) => (internalWords.test(text) ? fallback : text))
}

export const HiddenValuesNote =
    'PostHog shows field values only to the person who created the diff and project admins. Sensitive fields are always hidden.'
function containsHiddenValue(value: unknown): boolean {
    return (
        value === '[redacted]' ||
        (value !== null && typeof value === 'object' && Object.values(value).some(containsHiddenValue))
    )
}

function hidesPair(left: unknown, right: unknown): boolean {
    return (left === null && right === null) || containsHiddenValue(left) || containsHiddenValue(right)
}

const Field = z
    .object({ path: z.string(), before: z.json(), after: z.json(), sensitive: z.boolean() })
    .transform((field) => ({
        ...field,
        ...(field.sensitive || hidesPair(field.before, field.after)
            ? { before: null, after: null, hidden: true as const }
            : {}),
    }))
const Change = z.object({
    action: Action,
    kind: z.string(),
    key: z.string(),
    name: z.string(),
    summary: serviceText('Review the changed fields.'),
    entity_id: z.string().optional(),
    fields: z.array(Field),
    source: Location.nullish(),
    loses: serviceText('The existing entity is replaced. Review its history and links before pushing.').nullable(),
})
const DriftField = z
    .object({ path: z.string(), pushed: z.json(), found: z.json(), sensitive: z.boolean().optional() })
    .transform((field) => ({
        ...field,
        ...(field.sensitive || hidesPair(field.pushed, field.found)
            ? { pushed: null, found: null, hidden: true as const }
            : {}),
    }))
const Drift = z.object({
    kind: z.string(),
    key: z.string(),
    fields: z.array(DriftField),
    // PostHog's schema sends false for an entity that still exists. Only true means anything.
    deleted: z
        .boolean()
        .transform((deleted) => (deleted ? (true as const) : undefined))
        .optional(),
})
const ErrorCode = z
    .string()
    .regex(/^[a-z][a-z0-9_]*$/)
    .refine((code) => !internalWords.test(code))
    .catch('stack_failed')
const Problem = z
    .object({
        code: ErrorCode,
        message: serviceText('PostHog could not finish this stack operation.'),
        kind: z.string().optional(),
        key: z.string().optional(),
        path: z.string().optional(),
    })
    .transform((problem) =>
        problem.code === 'secret_literal' ? { ...problem, message: stackGuidance('secret_literal')![0] } : problem
    )
const WarningCode = z
    .string()
    .regex(/^[a-z][a-z0-9_]*$/)
    .refine((code) => !internalWords.test(code))
    .catch('unrecorded_create')
const Warning = z.object({
    code: WarningCode,
    kind: z.string(),
    key: z.string().nullable(),
    message: serviceText(
        'A push that stopped earlier may have created this without recording it. Check PostHog before pushing.'
    ),
    entities: z.array(z.object({ entity_id: z.string(), name: z.string() })),
})
const DiffBody = z
    .object({
        changes: z.array(Change),
        drift: z.array(Drift),
        errors: z.array(Problem),
        warnings: z.array(Warning).default([]),
        summary: z.object({
            create: z.int().nonnegative(),
            update: z.int().nonnegative(),
            recreate: z.int().nonnegative(),
            remove: z.int().nonnegative(),
            adopt: z.int().nonnegative(),
            rename: z.int().nonnegative(),
            release: z.int().nonnegative().optional(),
        }),
        notes: z.array(serviceText('Review the diff in PostHog before pushing.')).optional(),
    })
    .transform((diff) => ({
        ...diff,
        ...([...diff.changes, ...diff.drift].some((item) => item.fields.some((field) => field.hidden))
            ? { notes: [...(diff.notes ?? []), HiddenValuesNote] }
            : {}),
        summary: {
            ...diff.summary,
            release: diff.summary.release ?? diff.changes.filter((change) => change.action === 'release').length,
        },
    }))
const SavedAnswer = z.object({
    id: DiffId,
    status: z.enum(['running', 'ready', 'pushed', 'failed', 'stale']),
    diff: DiffBody.nullish(),
    source: Source.optional(),
    created_at: z.string().optional(),
    expires_at: z.string().optional(),
    stack_name: z.string().optional(),
    push_status: z.enum(['running', 'succeeded', 'failed', 'uncertain']).nullish(),
    push_errors: z.array(Problem).optional(),
})
const Entity = z.object({
    kind: z.string(),
    entity_id: z.string().min(1),
    name: z.string(),
    body: z.record(z.string(), z.json()),
})
const AdoptResource = z.object({ kind: z.string(), key: z.string(), entity_id: z.string() })
const AdoptRequest = z.object({ resources: z.array(AdoptResource).min(1) })
const Binding = AdoptResource.extend({
    id: z.string().optional(),
    stack_name: z.string().optional(),
    repository: z.string().optional(),
    entity_url: z.string().nullish(),
    source: Location.nullish(),
    status: z.enum(['pending', 'bound', 'detached']),
    owned_fields: z.array(z.string()).optional(),
})
const AdoptAnswer = z.object({ bindings: z.array(Binding) })

export type Diff = z.output<typeof DiffBody>
export type DiffWarning = z.output<typeof Warning>
const Reconciled = z.object({ stack_name: z.string(), diff_id: DiffId, acknowledged_warnings: z.int().nonnegative() })
export type StackSource = z.output<typeof Source>
export type Adoptable = z.output<typeof Entity>
export type SavedAnswer = z.output<typeof SavedAnswer>
type Binding = z.output<typeof Binding>
type AdoptAnswer = z.output<typeof AdoptAnswer>
type Reconciled = z.output<typeof Reconciled>

function savedOutcome(answer: SavedAnswer, expectedStack: string | undefined, expectedId?: string): SavedAnswer {
    if (
        (expectedId !== undefined && answer.id !== expectedId) ||
        (answer.stack_name !== undefined && answer.stack_name !== expectedStack)
    ) {
        throw new HogError(
            'unexpected_response',
            'PostHog returned a different diff or stack.',
            'Check the stack name and run hog diff again.'
        )
    }
    if (answer.push_status === 'uncertain') {
        const [message, hint] = stackGuidance('push_uncertain')!
        throw new HogError('push_uncertain', message, hint, undefined, { id: answer.id })
    }
    const problems = [...(answer.diff?.errors ?? []), ...(answer.push_errors ?? [])]
    // A push that fails after saving some of its work moves the stack, so its own diff reads as stale.
    // Its errors say what to fix, so they come before the moved stack.
    if (answer.status === 'stale' && !(answer.push_status === 'failed' && problems.length)) {
        throw movedError()
    }
    if (answer.status === 'failed' || answer.push_status === 'failed' || problems.length) {
        const code = problems[0]?.code ?? 'stack_failed'
        const guidance = stackGuidance(code)
        const lines = problems.map((problem) =>
            [problem.kind, problem.key, problem.path, problem.message].filter(Boolean).join(' ')
        )
        throw new HogError(
            code,
            lines.join('\n') || guidance?.[0] || 'PostHog could not finish this stack operation.',
            guidance?.[1] ?? 'Check the definitions and run hog diff again.',
            undefined,
            { id: answer.id, problems }
        )
    }
    return answer
}

const SecretName = z
    .string()
    .regex(
        /^[A-Za-z_][A-Za-z0-9_]{0,99}$/,
        'Use up to 100 letters, numbers or underscores, starting with a letter or underscore.'
    )
export const parseSecretName = (name: string, failure: ParseFailure): string => parseOrThrow(SecretName, name, failure)
const Secret = z.object({ name: SecretName, updated_at: z.iso.datetime({ offset: true }) })
const SecretList = z.object({ results: z.array(Secret) })
type StackSecret = z.output<typeof Secret>
const Scopes = z.array(z.string().refine(isScopeName))
const ScopeError = z.object({ extra: z.object({ required_scopes: Scopes.optional() }).optional() })
const SecretRequest = z.object({
    value: z
        .string()
        .min(1)
        .refine((value) => new TextEncoder().encode(value).length <= 65536, 'Use a secret of at most 64 KiB.'),
})
export const parseSecretValue = (value: string): string =>
    parseOrThrow(SecretRequest.shape.value, value, {
        code: 'invalid_secret_value',
        hint: 'Pass a non-empty value of at most 64 KiB.',
        exitCode: EXIT_USAGE,
    })

interface ProjectTarget {
    target: Context
    api: PostHogApi
    project: ProjectId
    serviceCall: <T>(call: Promise<T>, fallbackScope?: string, confidential?: boolean) => Promise<T>
    root: string
}

async function projectTarget(ctx: Context, stack: ResolvedStack): Promise<ProjectTarget> {
    const target = ctx.forProject(stack.environment)
    const api = await target.posthog()
    const { key } = await target.credentials()
    async function serviceCall<T>(call: Promise<T>, fallbackScope = 'stack:read', confidential = false): Promise<T> {
        try {
            return await call
        } catch (error) {
            if (error instanceof ApiError) {
                const scopes = ScopeError.safeParse(error.body).data?.extra?.required_scopes
                throw stackApiFailure(error, fallbackScope, key.status().kind, key.host, confidential, scopes)
            }
            if (confidential) {
                throw new HogError(
                    'secret_request_failed',
                    'PostHog could not confirm the result of this secret request.',
                    'Check your connection, then run hog stack secret list to review the names and dates.'
                )
            }
            if (error instanceof HogError && error.code === 'unexpected_response') {
                throw new HogError(
                    error.code,
                    'PostHog returned an unreadable stack response.',
                    'Check that hog and PostHog are up to date.'
                )
            }
            throw error
        }
    }
    return { target, api, project: key.projectId, serviceCall, root: `/api/projects/${key.projectId}/stacks/` }
}

export const languages = ['python', 'golang', 'typescript'] as const
const Module = z.object({
    content: z.string(),
    language: z.enum(languages),
    event_count: z.int().nonnegative(),
    schema_hash: z.string(),
    generator_version: z.string(),
})
export type GeneratedModule = z.output<typeof Module>

// A module is a pure function of the description, so it needs no stack name and PostHog stores nothing.
export async function generateModule(
    ctx: Context,
    stack: ResolvedStack,
    description: StackDescription,
    language: (typeof languages)[number]
): Promise<GeneratedModule> {
    const { api, root, serviceCall } = await projectTarget(ctx, stack)
    const body = parseOrThrow(
        z.object({ description: Description, language: z.enum(languages) }),
        { description, language },
        {
            code: 'invalid_description',
            hint: 'Run hog check and fix the definitions.',
        }
    )
    return serviceCall(
        api.post(
            `${root}modules/`,
            body,
            Module.refine((module) => module.language === language)
        )
    )
}

const StackSettings = z.object({ name: z.string(), context_pages_enabled: z.boolean() })
type StackSettings = z.output<typeof StackSettings>
type AdoptResource = z.input<typeof AdoptResource>

export interface StackService {
    project: ProjectId
    name: string
    setSecret(name: string, value: string): Promise<void>
    listSecrets(): Promise<StackSecret[]>
    removeSecret(name: string): Promise<void>
    create(description: StackDescription, source: StackSource): Promise<SavedAnswer>
    get(id: string, timeoutMs: number): Promise<SavedAnswer>
    push(id: string, maxRemovals?: number): Promise<SavedAnswer>
    adoptable(kind: string, limit: number, cursor?: string): Promise<Page<Adoptable>>
    reconcile(id: string): Promise<Reconciled>
    setContextPages(enabled: boolean): Promise<StackSettings>
    findAdoptable(kind: string, selectors: readonly string[]): Promise<Adoptable[]>
    prepareAdopt(): Promise<void>
    bind(resource: AdoptResource): Promise<Binding>
    adopt(resources: AdoptResource[]): Promise<AdoptAnswer>
}

export async function stackService(ctx: Context, stack: ResolvedStack): Promise<StackService> {
    if (!stack.name) {
        throw new HogError(
            'stack_unnamed',
            'This folder has no stack name.',
            'Run hog init to name the stack in posthog.json.',
            EXIT_USAGE
        )
    }
    const { target, api, project, serviceCall, root } = await projectTarget(ctx, stack)
    const path = `${root}${encodeURIComponent(stack.name)}/`
    const secretPath = (name: string): string => `${path}secrets/${encodeURIComponent(name)}/`
    const diffPath = (id: string): string => `${path}diffs/${encodeURIComponent(id)}/`
    const candidates = (kind: string, limit: number, cursor?: string): string => {
        const query = new URLSearchParams({ kind, limit: String(limit) })
        if (cursor !== undefined) {
            query.set('cursor', cursor)
        }
        return `${root}adoptable/?${query}`
    }
    return {
        project,
        name: stack.name,
        async setSecret(name: string, value: string): Promise<void> {
            const request = parseOrThrow(
                SecretRequest,
                { value },
                {
                    code: 'invalid_secret_value',
                    hint: 'Pass a non-empty value of at most 64 KiB.',
                    exitCode: EXIT_USAGE,
                }
            )
            await target.ensureScopes(['stack:write'])
            await serviceCall(
                api.withoutStepUp().put(
                    secretPath(name),
                    request,
                    Secret.refine((secret) => secret.name === name)
                ),
                'stack:write',
                true
            )
        },
        async listSecrets() {
            await target.ensureScopes(['stack:read'])
            return (await serviceCall(api.withoutStepUp().get(`${path}secrets/`, SecretList), 'stack:read', true))
                .results
        },
        async removeSecret(name: string): Promise<void> {
            await target.ensureScopes(['stack:write'])
            await serviceCall(api.withoutStepUp().delete(secretPath(name), z.undefined()), 'stack:write', true)
        },
        create(description: StackDescription, source: StackSource) {
            const body = parseOrThrow(
                StartRequest,
                { description, source },
                { code: 'invalid_description', hint: 'Run hog check and review the repository details.' }
            )
            return serviceCall(api.post(`${path}diffs/`, body, SavedAnswer)).then((answer) =>
                savedOutcome(answer, stack.name)
            )
        },
        get(id: string, timeoutMs: number) {
            return serviceCall(api.get(diffPath(id), SavedAnswer, { timeoutMs })).then((answer) =>
                savedOutcome(answer, stack.name, id)
            )
        },
        push(id: string, maxRemovals?: number) {
            const body = PushRequest.parse({ max_removals: maxRemovals })
            return serviceCall(api.post(`${diffPath(id)}push/`, body, SavedAnswer), 'stack:write').then((answer) =>
                savedOutcome(answer, stack.name, id)
            )
        },
        adoptable(kind: string, limit: number, cursor?: string) {
            return serviceCall(
                getPage(
                    api,
                    candidates(kind, limit, cursor),
                    Entity.refine((item) => item.kind === kind)
                )
            )
        },
        async reconcile(id: string) {
            await target.ensureScopes(['stack:write'])
            const name = stack.name
            return serviceCall(
                api.post(
                    `${path}reconcile/`,
                    { diff_id: id },
                    Reconciled.refine((answer) => answer.diff_id === id && answer.stack_name === name)
                ),
                'stack:write'
            )
        },
        async setContextPages(enabled: boolean) {
            await target.ensureScopes(['stack:write'])
            const name = stack.name
            return serviceCall(
                api.post(
                    `${path}context_pages/`,
                    { enabled },
                    StackSettings.refine(
                        (settings) => settings.name === name && settings.context_pages_enabled === enabled
                    )
                ),
                'stack:write'
            )
        },
        async findAdoptable(kind: string, selectors: readonly string[]): Promise<Adoptable[]> {
            const wanted = new Set(selectors)
            const byName = new Map<string, Adoptable | null>()
            const { found: byId, complete } = await serviceCall(
                findNamed(
                    api,
                    candidates(kind, 100),
                    Entity.refine((item) => item.kind === kind),
                    wanted,
                    (entity) => {
                        if (wanted.has(entity.name)) {
                            const previous = byName.get(entity.name)
                            byName.set(
                                entity.name,
                                previous === undefined || previous?.entity_id === entity.entity_id ? entity : null
                            )
                        }
                        return entity.entity_id
                    }
                )
            )
            const selected = new Map<string, Adoptable>()
            for (const selector of wanted) {
                const entity = byId.get(selector) ?? byName.get(selector)
                if (entity === null || (!byId.has(selector) && !complete)) {
                    throw new HogError(
                        'adoption_ambiguous',
                        `Could not match ${selector} to a single entity.`,
                        'List the available entities with hog pull --adopt and select by ID.',
                        EXIT_USAGE
                    )
                }
                if (!entity) {
                    throw new HogError(
                        'adoption_missing',
                        `No entity available to adopt matches ${selector}.`,
                        'List the available entities with hog pull --adopt and check the IDs.',
                        EXIT_USAGE
                    )
                }
                selected.set(entity.entity_id, entity)
            }
            return [...selected.values()]
        },
        prepareAdopt(): Promise<void> {
            return target.ensureScopes(['stack:write'], 'adopt these entities')
        },
        // Binds an entity to a definition that is already in the folder, so nothing is written on disk.
        async bind(resource: AdoptResource) {
            await target.ensureScopes(['stack:write'], 'bind this entity')
            const body = parseOrThrow(
                AdoptRequest,
                { resources: [resource] },
                { code: 'invalid_adoption', hint: 'Check the kind, key and entity ID.', exitCode: EXIT_USAGE }
            )
            const answer = await serviceCall(api.post(`${path}adopt/`, body, AdoptAnswer), 'stack:write')
            const binding = answer.bindings.find(
                (item) =>
                    item.kind === resource.kind &&
                    item.key === resource.key &&
                    item.entity_id === resource.entity_id &&
                    item.status !== 'detached'
            )
            if (!binding) {
                throw new HogError(
                    'adoption_unconfirmed',
                    'PostHog did not confirm the binding.',
                    'Run hog diff to check whether the entity is bound before trying again.'
                )
            }
            return binding
        },
        async adopt(resources: AdoptResource[]) {
            const body = parseOrThrow(
                AdoptRequest,
                { resources },
                { code: 'invalid_adoption', hint: 'Select at least one entity and check its kind, key and ID.' }
            )
            const answer = await serviceCall(api.post(`${path}adopt/`, body, AdoptAnswer), 'stack:write').catch(
                (error: unknown) => {
                    if (!(error instanceof HogError)) {
                        throw error
                    }
                    const refused = error.details?.status === 403 || (error instanceof ApiError && error.status === 403)
                    const next = refused
                        ? 'Recording bindings needs stack:write in this project. Retry the same selection once you have access.'
                        : 'Run hog diff to check the bindings before retrying the same selection.'
                    throw new HogError(
                        error.code,
                        error.message,
                        [error.hint, 'The definitions are on disk.', next].filter(Boolean).join(' '),
                        error.exitCode,
                        error instanceof ApiError ? { ...error.details, status: error.status } : error.details,
                        error.serverDetail
                    )
                }
            )
            const identity = (item: AdoptResource): string => JSON.stringify([item.kind, item.key, item.entity_id])
            const confirmed = new Set(answer.bindings.filter((binding) => binding.status !== 'detached').map(identity))
            if (confirmed.size !== resources.length || resources.some((item) => !confirmed.has(identity(item)))) {
                throw new HogError(
                    'adoption_unconfirmed',
                    'PostHog did not confirm each requested binding.',
                    'The definitions are on disk. Review the bindings in PostHog before retrying the adoption.'
                )
            }
            return answer
        },
    }
}
