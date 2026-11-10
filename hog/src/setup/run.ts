import { join } from 'node:path'
import { z } from 'zod'

import type { InstallableSkill } from '@posthog/mcp/src/cli/library-types'

import { continueApproval, refuseInCi, reusablePending } from '@/core/approval'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import type { Choice } from '@/core/prompts'
import type { AccessKey } from '@/posthog/access-key'
import { CI_CREDENTIALS_HINT, type Credentials } from '@/posthog/credentials'
import { LOGIN_SCOPES } from '@/posthog/device-auth'
import { cloudRegion, INGESTION_HOSTS, REGIONS, regionOf, type Host, type RegionId } from '@/posthog/host'
import { parseProjectId } from '@/posthog/ids'
import { configNames, finishLogin, nameInConfig } from '@/posthog/login/finish'
import { loginFlow, saveLogin, SETUP_COMMAND } from '@/posthog/login/flow'
import { runHogQL } from '@/posthog/query'
import { ProjectTokenSchema, type ProjectToken } from '@/posthog/tokens'

import { AGENTS_FILE, blockStage, earlyBlock, finalBlock, writeBlock, type WrittenFile } from './agents-md'
import { chosenFirst, INSTALL_SKILL, knownProduct, loadProducts, type Product } from './products'
import {
    hasRead,
    readState,
    setupScope,
    STEP_IDS,
    updateState,
    type SetupScope,
    type SetupState,
    type SkillFile,
    type StepId,
} from './state'

const SETUP_NEXT = SETUP_COMMAND
const SKILL_READ: SkillFile = { skill: INSTALL_SKILL, path: 'SKILL.md' }
const RULES_READ: SkillFile = { skill: INSTALL_SKILL, path: 'references/COMMANDMENTS.md' }
// Logins that can't serve this folder, so the login step starts a new one.
const NO_LOGIN_CODES = new Set(['not_authenticated', 'project_mismatch', 'host_mismatch', 'session_expired'])
// A client clock can run behind PostHog's, so events count by when PostHog received them, and the
// timestamp bound only keeps the query on recent partitions.
const CLOCK_SKEW = 'interval 1 day'
const SUMMARY_EVENTS_WINDOW_MS = 24 * 60 * 60 * 1000

export interface SetupInput {
    next: boolean
    reason?: string
    products?: string[]
    region?: RegionId
    reviewed?: boolean
    productsAck?: boolean
    installSkills?: string[]
}

interface QuestionChoice {
    value: string
    label: string
    description: string | null
}

export interface Question {
    id: 'reason' | 'products' | 'region' | 'skills'
    question: string
    option: string
    multiple: boolean
    choices?: QuestionChoice[]
}

export type NextAction =
    | { kind: 'run'; command: string; instructions: string }
    | { kind: 'ask_user'; ask: Question[]; command: string; instructions: string }
    | { kind: 'read'; read: string[]; command: string; instructions: string }
    | { kind: 'wait'; command: string; url: string; code: string | null; expiresAt: string; instructions: string }
    | { kind: 'done'; instructions: string }

export interface DoneStep {
    step: StepId
    summary: string
}

interface EventsContext {
    since: string
    // Null when hog didn't count, as `hog setup` doesn't at the verify step.
    count: number | null
    query: string
}

export interface SetupContext {
    folder: string
    configPath: string | null
    host: string | null
    projectId: string | null
    region: RegionId | null
    token?: ProjectToken
    apiHost?: string
    loggedIn?: boolean
    agentsMd?: WrittenFile[]
    events?: EventsContext
    products?: (Product & { chosen: boolean })[]
    installableSkills?: { id: string; name: string; description: string }[]
    installedSkills?: { id: string; directory: string | null; status: 'installed' | 'already_installed' }[]
    warnings: string[]
}

export interface SetupResult {
    step: StepId
    status: 'in_progress' | 'connected'
    // Why `hog setup next` stopped, for scripts. Null once connected.
    code: string | null
    done: DoneStep[]
    next: NextAction
    context: SetupContext
}

interface Stop {
    code: string
    next: NextAction
}

const ProjectSchema = z.looseObject({ api_token: ProjectTokenSchema })
const CountSchema = z.number().or(z.string().regex(/^\d+$/).transform(Number))

function readCommand({ skill, path }: SkillFile): string {
    return path === 'SKILL.md' ? `hog learn ${skill}` : `hog learn ${skill} ${path}`
}

function promptChoices(choices: readonly QuestionChoice[]): Choice<string>[] {
    return choices.map(({ value, label, description }) => ({ value, label, hint: description ?? undefined }))
}

function eventsQuery(since: string): string {
    return `select count() from events where created_at >= toDateTime('${since}') and timestamp >= toDateTime('${since}') - ${CLOCK_SKEW}`
}

function eventsContext(startedAt: number, count: number | null): EventsContext {
    const since = new Date(startedAt).toISOString()
    return { since, count, query: eventsQuery(since) }
}

class SetupRun {
    readonly done: DoneStep[] = []
    readonly context: SetupContext
    firstStep: StepId | undefined
    private productList?: Promise<Product[]>

    constructor(
        readonly ctx: Context,
        readonly input: SetupInput,
        readonly scope: SetupScope,
        public state: SetupState | undefined
    ) {
        this.context = {
            folder: scope.folder,
            configPath: null,
            host: null,
            projectId: null,
            region: null,
            warnings: [],
        }
    }

    // Steps an agent finishes count only on a `hog setup next` that started on them, so the agent
    // always sees a step's instructions before the step ends.
    startedOn(step: StepId): boolean {
        return this.input.next && this.firstStep === step
    }

    // The login for this folder's host and project. Undefined when there is none, or when only a
    // login to another project could serve it. `ctx` caches it until a step reloads `ctx`.
    async credentials(): Promise<Credentials | undefined> {
        try {
            const credentials = await this.ctx.credentials()
            return credentials.source === 'store' && credentials.choice.match === 'fallback' ? undefined : credentials
        } catch (error) {
            if (error instanceof HogError && NO_LOGIN_CODES.has(error.code)) {
                return undefined
            }
            throw error
        }
    }

    async key(): Promise<AccessKey> {
        const credentials = await this.credentials()
        if (!credentials) {
            throw new HogError('not_authenticated', 'hog has no login for this folder.', `Run \`${SETUP_NEXT}\`.`)
        }
        return credentials.key
    }

    products(): Promise<Product[]> {
        this.productList ??= loadProducts(this.ctx)
        return this.productList
    }

    async productsContext(): Promise<SetupContext['products']> {
        const chosen = this.state?.products ?? []
        return chosenFirst(await this.products(), chosen).map((product) => ({
            ...product,
            chosen: chosen.includes(product.id),
        }))
    }

    async complete(step: StepId): Promise<void> {
        this.state = await updateState(this.ctx, this.scope, (current) => {
            const base = current ?? this.state
            return !base || base.completed.includes(step) ? base : { ...base, completed: [...base.completed, step] }
        })
        this.ctx.telemetry.capture('hog setup step completed', { step })
    }

    async loginHost(): Promise<Host> {
        const configHost = (await this.ctx.config())?.config.host
        return (
            this.ctx.globals.host ?? cloudRegion(configHost) ?? this.state?.host ?? REGIONS[this.state?.region ?? 'us']
        )
    }

    async fillLoginContext(): Promise<void> {
        const credentials = await this.credentials()
        const loaded = await this.ctx.config()
        const host = credentials?.key.host ?? loaded?.config.host
        this.context.host = host ?? null
        this.context.projectId = credentials?.key.projectId ?? loaded?.config.projectId?.toString() ?? null
        this.context.region = regionOf(host) ?? null
        this.context.configPath = loaded?.path ?? null
        this.context.loggedIn = credentials !== undefined
    }
}

interface StepDefinition {
    // Defaults to the step being in the state file's completed list.
    isDone?(run: SetupRun): Promise<boolean>
    summary(run: SetupRun): Promise<string> | string
    // Does the step on `hog setup next`, or says what `next` will do on `hog setup`. Returns
    // undefined once the step is done, or what has to happen first.
    advance(run: SetupRun): Promise<Stop | undefined>
}

function completed(run: SetupRun, step: StepId): boolean {
    return run.state?.completed.includes(step) ?? false
}

function runNext(code: string, instructions: string): Stop {
    return { code, next: { kind: 'run', command: SETUP_NEXT, instructions } }
}

interface PurposeQuestion {
    question: string
    help: string
    choices?: QuestionChoice[]
}

function purposeQuestions(
    products: readonly Product[],
    telemetry: boolean
): Record<'reason' | 'products' | 'region', PurposeQuestion> {
    return {
        reason: {
            question: 'Why are you adding PostHog to this app?',
            help: telemetry
                ? 'hog sends the answer to PostHog, to improve setup.'
                : 'hog keeps the answer on this machine.',
        },
        products: {
            question: 'Which PostHog products interest you?',
            help: 'Pick any, or none.',
            choices: products.map(({ id, label, description }) => ({ value: id, label, description })),
        },
        region: {
            question: 'Where should your PostHog data be hosted?',
            help: 'With an account already, pick where it is hosted. For a new account, EU Cloud keeps the data in the EU.',
            choices: [
                { value: 'us', label: 'US Cloud', description: 'us.posthog.com' },
                { value: 'eu', label: 'EU Cloud', description: 'eu.posthog.com' },
            ],
        },
    }
}

function purposeCommand(withRegion: boolean): string {
    return `${SETUP_NEXT} --reason "<why>" --products <id,id>${withRegion ? ' --region <us|eu>' : ''}`
}

const purpose: StepDefinition = {
    isDone: async (run) => run.state !== undefined,
    summary: (run) => {
        const picked = (run.state?.products ?? []).map((id) => knownProduct(id).label)
        return picked.length > 0 ? `Interested in ${picked.join(', ')}` : 'Answered why you are adding PostHog'
    },
    async advance(run) {
        const { ctx, input } = run
        const configHost = (await ctx.config())?.config.host
        const needsRegion = ctx.globals.host === undefined && cloudRegion(configHost) === undefined
        const products = await run.products()
        const questions = purposeQuestions(products, ctx.telemetry.isEnabled)
        let { reason, products: picked, region } = input
        const prompts = input.next ? ctx.prompts : undefined
        if (prompts) {
            reason ??= await prompts.text(questions.reason.question, {
                help: questions.reason.help,
                validate: (value) => (value.trim() ? undefined : 'Write a few words about it.'),
            })
            picked ??= await prompts.multiselect(
                questions.products.question,
                promptChoices(questions.products.choices ?? []),
                { help: 'Space picks a product, Enter goes on. Picking none is fine.' }
            )
            if (needsRegion) {
                region ??= (await prompts.select(
                    questions.region.question,
                    promptChoices(questions.region.choices ?? []),
                    { help: questions.region.help }
                )) as RegionId
            }
        }
        const missing = {
            reason: reason === undefined,
            products: picked === undefined,
            region: needsRegion && region === undefined,
        }
        if (reason === undefined || picked === undefined || missing.region) {
            const ask = (['reason', 'products', 'region'] as const)
                .filter((id) => missing[id])
                .map(
                    (id): Question => ({
                        id,
                        question: `${questions[id].question} ${questions[id].help}`,
                        option: `--${id}`,
                        multiple: id === 'products',
                        choices: questions[id].choices,
                    })
                )
            const given = input.reason !== undefined || input.products !== undefined || input.region !== undefined
            if (input.next && given) {
                throw new HogError(
                    'setup_needs_answers',
                    `hog setup next needs ${ask.map((question) => question.option).join(', ')} too.`,
                    `Ask the user, then pass every answer at once: ${purposeCommand(needsRegion)}. Product options: ${products.map((product) => product.id).join(', ')}.`,
                    EXIT_USAGE
                )
            }
            return {
                code: 'setup_needs_answers',
                next: {
                    kind: 'ask_user',
                    ask,
                    command: purposeCommand(needsRegion),
                    instructions:
                        'Ask the user these questions, then run the command with their answers. Pass --products none when they pick none.',
                },
            }
        }
        const unknown = picked.filter((id) => !products.some((product) => product.id === id))
        if (unknown.length > 0) {
            throw new HogError(
                'setup_unknown_product',
                `hog doesn't know the product ${unknown.join(', ')}.`,
                `Pass products from this list: ${products.map((product) => product.id).join(', ')}.`,
                EXIT_USAGE
            )
        }
        const answers = { reason, products: picked, region: needsRegion ? (region ?? 'us') : null }
        run.state = {
            folder: run.scope.folder,
            startedAt: ctx.runtime.now(),
            ...answers,
            host: ctx.globals.host ?? null,
            reads: [],
            completed: [],
        }
        // The reason is the one text a person typed that telemetry carries, because the question says so.
        ctx.telemetry.capture('hog setup started', answers)
        await run.complete('purpose')
        return undefined
    },
}

function waitFor(
    { url, code, expiresAt }: { url: string; code: string | null; expiresAt: string },
    projectId: string | undefined
): Stop {
    const approve = code ? `open ${url} and approve the code ${code}` : `open ${url} and approve it`
    const pick = projectId ? `, picking project ${projectId}, which posthog.json names` : ''
    return {
        code: 'setup_login_pending',
        next: {
            kind: 'wait',
            command: SETUP_NEXT,
            url,
            code,
            expiresAt,
            instructions: `Ask the user to ${approve}${pick}. New users can sign up on the same page. Then run \`${SETUP_NEXT}\`, which returns once they approve. If it times out, run it again.`,
        },
    }
}

// posthog.json comes with the repository, so a login to another project must not rename its project.
async function checkProject(run: SetupRun, key: AccessKey, named: string | undefined): Promise<void> {
    if (named === undefined || parseProjectId(named) === key.projectId) {
        return
    }
    // The login works for its own project, so hog keeps it.
    await saveLogin(run.ctx.runtime, key)
    throw new HogError(
        'setup_project_mismatch',
        `You approved project ${key.projectId}, and posthog.json names project ${named}.`,
        `Run \`${SETUP_NEXT}\` and pick project ${named} on the approval page. To set up project ${key.projectId} instead, change "projectId" in posthog.json first.`,
        EXIT_USAGE
    )
}

const login: StepDefinition = {
    isDone: async (run) => (await run.credentials()) !== undefined,
    summary: async (run) => {
        const key = await run.key()
        return `Logged in to ${key.host}, project ${key.projectId}`
    },
    async advance(run) {
        const { ctx } = run
        const host = await run.loginHost()
        const named = (await ctx.config())?.config.projectId?.toString()
        const flow = loginFlow(ctx.runtime, host, LOGIN_SCOPES, {
            command: SETUP_COMMAND,
            pendingName: run.scope.pendingName,
        })
        if (!run.input.next) {
            const pending = await reusablePending(ctx.runtime, flow)
            return pending
                ? waitFor(
                      {
                          url: pending.url,
                          code: pending.userCode,
                          expiresAt: new Date(pending.expiresAt).toISOString(),
                      },
                      named
                  )
                : runNext(
                      'setup_login_needed',
                      `Run \`${SETUP_NEXT}\`. hog starts a login to ${host}, and new users can sign up on the same page.`
                  )
        }
        refuseInCi(ctx, SETUP_NEXT, CI_CREDENTIALS_HINT)
        const approval = await continueApproval(ctx, flow)
        if (approval.status === 'pending') {
            return waitFor(approval, named)
        }
        await checkProject(run, approval.value, named)
        const { config } = await finishLogin(ctx, approval.value)
        if (config.status === 'failed') {
            // Commands here pick the login from posthog.json, so setup can't go on without it.
            throw new HogError(
                'setup_config_unwritable',
                `You're logged in, and hog couldn't write ${config.path}: ${config.error ?? 'unknown error'}`,
                `Make ${run.scope.folder} writable, or add "host": "${host}" and "projectId": ${approval.value.projectId} to posthog.json yourself. Then run \`${SETUP_NEXT}\`.`
            )
        }
        await run.complete('login')
        return undefined
    },
}

// A failed intent only costs PostHog a hint about what to show first, so it warns and setup goes on.
async function recordIntents(run: SetupRun): Promise<void> {
    const intents = (run.state?.products ?? []).map(knownProduct).filter((product) => product.intent !== null)
    if (intents.length === 0) {
        return
    }
    const api = (await run.ctx.posthog()).withoutStepUp()
    const results = await Promise.allSettled(
        intents.map((product) =>
            api.patch(
                'add_product_intent/',
                { product_type: product.intent, metadata: { source: 'hog setup' } },
                z.unknown()
            )
        )
    )
    results.forEach((result, index) => {
        if (result.status === 'rejected') {
            const reason = result.reason instanceof Error ? result.reason.message : String(result.reason)
            run.context.warnings.push(`PostHog didn't record your interest in ${intents[index]?.label}: ${reason}`)
        }
    })
}

const project: StepDefinition = {
    isDone: async (run) => {
        const key = (await run.credentials())?.key
        return completed(run, 'project') && key !== undefined && configNames((await run.ctx.config())?.config, key)
    },
    summary: async (run) => {
        const key = await run.key()
        return `posthog.json names project ${key.projectId} on ${key.host}`
    },
    async advance(run) {
        if (!run.input.next) {
            return runNext(
                'setup_project_pending',
                `Run \`${SETUP_NEXT}\`. hog names the project in posthog.json and tells PostHog which products you picked.`
            )
        }
        const key = await run.key()
        const named = await nameInConfig(run.ctx, key)
        if (named.status === 'failed') {
            throw new HogError(
                'setup_config_unwritable',
                `hog couldn't write ${named.path}: ${named.error ?? 'unknown error'}`,
                `Check that you can write to ${run.scope.folder}, then run \`${SETUP_NEXT}\` again.`
            )
        }
        if (named.status !== 'unchanged') {
            run.ctx.reload()
        }
        await recordIntents(run)
        await run.complete('project')
        return undefined
    },
}

const agentsMd: StepDefinition = {
    isDone: async (run) =>
        completed(run, 'agents-md') && (await blockStage(run.ctx.runtime, run.scope.folder)) !== undefined,
    summary: (run) => {
        const changed = run.context.agentsMd?.filter((file) => file.status !== 'unchanged')
        return changed?.length
            ? `Added the PostHog setup note to ${changed.map((file) => file.path).join(' and ')}`
            : 'AGENTS.md has the PostHog setup note'
    },
    async advance(run) {
        if (!run.input.next) {
            return runNext(
                'setup_agents_md_pending',
                `Run \`${SETUP_NEXT}\`. hog adds a note to AGENTS.md so later sessions continue this setup.`
            )
        }
        run.context.agentsMd = await writeBlock(run.ctx.runtime, run.scope.folder, earlyBlock())
        await run.complete('agents-md')
        return undefined
    },
}

async function fillInstallContext(run: SetupRun): Promise<void> {
    const key = await run.key()
    const project = await (await run.ctx.posthog()).get('', ProjectSchema)
    const region = regionOf(key.host)
    run.context.token = project.api_token
    run.context.apiHost = region ? INGESTION_HOSTS[region] : key.host
}

const install: StepDefinition = {
    summary: () => 'Read the install skill and installed PostHog',
    async advance(run) {
        await fillInstallContext(run)
        const state = run.state
        const read = state !== undefined && hasRead(state, SKILL_READ) && hasRead(state, RULES_READ)
        if (read && run.startedOn('install')) {
            await run.complete('install')
            return undefined
        }
        if (read) {
            return runNext(
                'setup_install_pending',
                `Install PostHog in this app as the skill says, with the project token and host shown here. Then run \`${SETUP_NEXT}\`.`
            )
        }
        return {
            code: 'setup_skill_not_read',
            next: {
                kind: 'read',
                read: [readCommand(SKILL_READ), readCommand(RULES_READ)],
                command: SETUP_NEXT,
                instructions: `Run both commands and follow the skill to install PostHog in this app, with the project token and host shown here. Then run \`${SETUP_NEXT}\`.`,
            },
        }
    },
}

const review: StepDefinition = {
    summary: () => 'Checked the changes against the install rules',
    async advance(run) {
        if (run.input.reviewed && run.startedOn('review')) {
            await run.complete('review')
            return undefined
        }
        return {
            code: 'setup_not_reviewed',
            next: {
                kind: 'read',
                read: [readCommand(RULES_READ)],
                command: `${SETUP_NEXT} --reviewed`,
                instructions: `Read the rules again and check each one against the changes you made. Fix any change that breaks a rule, then run \`${SETUP_NEXT} --reviewed\`.`,
            },
        }
    },
}

async function countEvents(run: SetupRun, startedAt: number): Promise<number> {
    const { query } = eventsContext(startedAt, null)
    const response = await runHogQL((await run.ctx.posthog()).withoutStepUp(), query)
    return CountSchema.catch(0).parse(response.results[0]?.[0])
}

const verify: StepDefinition = {
    summary: () => 'Events arrived in PostHog',
    async advance(run) {
        const startedAt = run.state?.startedAt ?? 0
        const { since } = eventsContext(startedAt, null)
        const ask = `Run the app and do something in it that sends an event, then run \`${SETUP_NEXT}\`. hog looks for events PostHog received since ${since}.`
        if (!run.input.next) {
            run.context.events = eventsContext(startedAt, null)
            return runNext('setup_no_events_yet', ask)
        }
        const count = await countEvents(run, startedAt)
        run.context.events = eventsContext(startedAt, count)
        if (count > 0) {
            await run.complete('verify')
            return undefined
        }
        return runNext('setup_no_events_yet', `PostHog has no events from this setup yet. ${ask}`)
    },
}

async function installSkills(run: SetupRun, ids: readonly string[], known: readonly InstallableSkill[]): Promise<void> {
    const unknown = ids.filter((id) => !known.some((skill) => skill.id === id))
    if (unknown.length > 0) {
        throw new HogError(
            'setup_unknown_skill',
            `There is no PostHog skill to install named ${unknown.join(', ')}.`,
            `Pass ids from installableSkills in \`hog setup\`: ${known.map((skill) => skill.id).join(', ')}.`,
            EXIT_USAGE
        )
    }
    run.context.installedSkills = []
    if (ids.length === 0) {
        return
    }
    const library = await run.ctx.skills()
    for (const id of ids) {
        const result = await library.install(id, { cwd: run.scope.folder })
        if (result.ok) {
            run.context.installedSkills.push({ id, directory: result.value.skill.directory, status: 'installed' })
        } else if (result.error.code === 'already_installed') {
            run.context.installedSkills.push({ id, directory: null, status: 'already_installed' })
        } else {
            throw new HogError(
                'skill_install_failed',
                `hog couldn't install the skill ${id}: ${result.error.message}`,
                `Run \`${SETUP_NEXT} --install-skills ${ids.join(',')}\` again, or leave --install-skills out to skip it.`
            )
        }
    }
}

// A list that fails to load only leaves the skills out of the products step.
async function installable(run: SetupRun): Promise<InstallableSkill[]> {
    let failure: string
    try {
        const result = await (await run.ctx.skills()).installable()
        if (result.ok) {
            return result.value.skills
        }
        failure = result.error.message
    } catch (error) {
        failure = error instanceof Error ? error.message : String(error)
    }
    run.context.warnings.push(`hog couldn't list the PostHog skills to install: ${failure}`)
    return []
}

function skillsQuestion(skills: readonly InstallableSkill[]): Question {
    return {
        id: 'skills',
        question:
            'Install PostHog skills into this repository, so later agent sessions can use them? Pick any, or none.',
        option: '--install-skills',
        multiple: true,
        choices: skills.map((skill) => ({ value: skill.id, label: skill.name, description: skill.description })),
    }
}

const productsStep: StepDefinition = {
    summary: () => 'Went through what else PostHog can do',
    async advance(run) {
        const { ctx, input } = run
        // Both load the same skills release, so they share one download.
        const [products, skills] = await Promise.all([run.productsContext(), installable(run)])
        run.context.products = products
        run.context.installableSkills = skills.map(({ id, name, description }) => ({ id, name, description }))
        const question = skills.length > 0 ? skillsQuestion(skills) : undefined
        const acknowledged = input.productsAck === true || input.installSkills !== undefined
        const prompts = input.next ? ctx.prompts : undefined
        if (prompts && !acknowledged) {
            prompts.note(
                (products ?? []).map((product) => `${product.label}: ${product.command}`).join('\n'),
                'What else PostHog can do'
            )
            const picked = question
                ? await prompts.multiselect(question.question, promptChoices(question.choices ?? []), {
                      help: 'Space picks a skill, Enter goes on.',
                  })
                : []
            await installSkills(run, picked, skills)
            await run.complete('products')
            return undefined
        }
        // A person at the terminal typed the options, so they count without the step's instructions first.
        if (acknowledged && (prompts !== undefined || run.startedOn('products'))) {
            await installSkills(run, input.installSkills ?? [], skills)
            await run.complete('products')
            return undefined
        }
        return {
            code: 'setup_products_pending',
            next: {
                kind: 'ask_user',
                ask: question ? [question] : [],
                command: `${SETUP_NEXT} --products-ack`,
                instructions: `Tell the user what else PostHog can do, from the products list${question ? ', and ask the question' : ''}. Then run \`${SETUP_NEXT} --products-ack\`${question ? ', with --install-skills <id,id> for the skills they picked' : ''}.`,
            },
        }
    },
}

async function writeFinalBlock(run: SetupRun): Promise<WrittenFile[]> {
    const key = await run.key()
    const body = finalBlock({
        host: key.host,
        projectId: key.projectId,
        products: await run.products(),
        chosen: run.state?.products ?? [],
    })
    return writeBlock(run.ctx.runtime, run.scope.folder, body)
}

const connected: StepDefinition = {
    summary: () => 'Wrote the final PostHog note to AGENTS.md',
    async advance(run) {
        if (!run.input.next) {
            return runNext(
                'setup_connect_pending',
                `Run \`${SETUP_NEXT}\`. hog rewrites the note in AGENTS.md with the commands for later PostHog work.`
            )
        }
        run.context.agentsMd = await writeFinalBlock(run)
        const startedAt = run.state?.startedAt ?? run.ctx.runtime.now()
        await run.complete('connected')
        run.ctx.telemetry.capture('hog setup completed', {
            products: run.state?.products ?? [],
            duration_ms: run.ctx.runtime.now() - startedAt,
        })
        return undefined
    },
}

const STEPS: Record<StepId, StepDefinition> = {
    purpose,
    login,
    project,
    'agents-md': agentsMd,
    install,
    review,
    verify,
    products: productsStep,
    connected,
}

function isDone(run: SetupRun, id: StepId): Promise<boolean> {
    return STEPS[id].isDone?.(run) ?? Promise.resolve(completed(run, id))
}

// Once connected, `hog setup` reports the folder instead of a step. A clone without hog's state
// file counts as connected when its AGENTS.md has the final note and posthog.json names a project.
async function summary(run: SetupRun): Promise<SetupResult> {
    await run.fillLoginContext()
    const loggedIn = run.context.loggedIn === true
    const state = run.state
    // The verify step of this call already counted. Otherwise the summary still shows without the
    // count, such as when the login lacks query:read.
    // The count covers the last day at most, so a folder connected long ago doesn't scan every event since.
    const since = state && Math.max(state.startedAt, run.ctx.runtime.now() - SUMMARY_EVENTS_WINDOW_MS)
    const counting =
        since !== undefined && loggedIn && run.context.events?.count == null
            ? countEvents(run, since).then(
                  (count) => eventsContext(since, count),
                  () => eventsContext(since, null)
              )
            : Promise.resolve(run.context.events)
    const [events, products] = await Promise.all([counting, run.productsContext()])
    run.context.events = events
    run.context.products = products
    run.context.agentsMd ??= [{ path: join(run.scope.folder, AGENTS_FILE), status: 'unchanged' }]
    if (run.done.length === 0) {
        for (const id of STEP_IDS) {
            if (await isDone(run, id)) {
                run.done.push({ step: id, summary: await STEPS[id].summary(run) })
            }
        }
    }
    return {
        step: 'connected',
        status: 'connected',
        code: null,
        done: run.done,
        context: run.context,
        next: loggedIn
            ? {
                  kind: 'done',
                  instructions:
                      'PostHog is set up in this folder. The note in AGENTS.md lists the commands for later PostHog work.',
              }
            : {
                  kind: 'run',
                  command: 'hog auth login',
                  instructions: 'PostHog is set up in this folder. Log in to use hog here.',
              },
    }
}

async function cloneIsConnected(run: SetupRun): Promise<boolean> {
    const config = (await run.ctx.config())?.config
    return (
        config?.host !== undefined &&
        config.projectId !== undefined &&
        (await blockStage(run.ctx.runtime, run.scope.folder)) === 'final'
    )
}

// `hog setup` (next false) only describes. `hog setup next` does the current step and every step
// after it hog can do alone, and stops at the first one that needs a person or the agent.
export async function runSetup(ctx: Context, input: SetupInput): Promise<SetupResult> {
    const scope = await setupScope(ctx)
    const run = new SetupRun(ctx, input, scope, await readState(ctx, scope))
    if (completed(run, 'connected') || (run.state === undefined && (await cloneIsConnected(run)))) {
        return summary(run)
    }
    for (const id of STEP_IDS) {
        if (!(await isDone(run, id))) {
            run.firstStep ??= id
            const stop = await STEPS[id].advance(run)
            if (stop) {
                await run.fillLoginContext()
                return { step: id, status: 'in_progress', ...stop, done: run.done, context: run.context }
            }
        }
        run.done.push({ step: id, summary: await STEPS[id].summary(run) })
    }
    return summary(run)
}
