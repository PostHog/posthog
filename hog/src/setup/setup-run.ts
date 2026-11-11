import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import type { PostHogApi } from '@/posthog/api'
import { cloudRegion, REGIONS, sameHost, type Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'
import { loginFor, readSettings, type LoginRecord } from '@/posthog/settings'

import { chosenFirst, loadProducts, type Product } from './products'
import type { DoneStep, SetupContext, SetupInput, Stop } from './result'
import { SETUP_NEXT, updateState, type SetupScope, type SetupState, type StepId } from './state'

// One step of the setup. Each one lives in its own file under `steps/`.
export interface Step {
    // Defaults to the step being in the state file's completed list.
    isDone?(run: SetupRun): Promise<boolean>
    summary(run: SetupRun): Promise<string> | string
    // Does the step on `hog setup next`, or says what `next` will do on `hog setup`. Returns
    // undefined once the step is done, or what has to happen first.
    advance(run: SetupRun): Promise<Stop | undefined>
}

export function completed(run: SetupRun, step: StepId): boolean {
    return run.state?.completed.includes(step) ?? false
}

export function runNext(code: string, instructions: string): Stop {
    return { code, next: { kind: 'run', command: SETUP_NEXT, instructions } }
}

// One call of `hog setup` or `hog setup next`, and what the steps found along the way.
export class SetupRun {
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
            loggedIn: false,
            warnings: [],
        }
    }

    // A step an agent finishes without giving an answer counts only on a `hog setup next` that
    // started on it, so the agent always sees the step's instructions before the step ends.
    startedOn(step: StepId): boolean {
        return this.input.next && this.firstStep === step
    }

    // The host something names: --host or HOG_HOST, or posthog.json when it names PostHog Cloud.
    async namedHost(): Promise<Host | undefined> {
        return this.ctx.globals.host ?? cloudRegion((await this.ctx.config())?.config.host)
    }

    // The host and project this folder's login is for. HOG_PROJECT_ID overrides posthog.json, as it
    // does for every command. The project is undefined until one of them names it.
    async target(): Promise<{ host: Host; projectId: ProjectId | undefined }> {
        const [named, query] = await Promise.all([this.namedHost(), this.ctx.loginQuery()])
        const host = named ?? this.state?.host ?? REGIONS.us

        const { configHost, configProjectId } = query
        const fromConfig = configHost === undefined || sameHost(configHost, host) ? configProjectId : undefined

        return { host, projectId: query.projectId ?? fromConfig }
    }

    // This folder's login, from settings.json, without reading its secret.
    async login(): Promise<LoginRecord | undefined> {
        const { host, projectId } = await this.target()
        return projectId === undefined ? undefined : loginFor(await readSettings(this.ctx.runtime), { host, projectId })
    }

    async requireLogin(): Promise<LoginRecord> {
        const login = await this.login()
        if (!login) {
            throw new HogError('not_authenticated', 'This folder has no login yet.', `Run \`${SETUP_NEXT}\`.`)
        }

        return login
    }

    // Every API call of setup goes through this, so the token it reports, the events it checks and the
    // posthog.json it writes are for one project. A key from HOG_PERSONAL_API_KEY or --dotenv-file
    // wins over the stored login and can be for another project, so setup refuses it.
    async api(): Promise<PostHogApi> {
        const [login, credentials] = await Promise.all([this.requireLogin(), this.ctx.credentials()])
        const { key } = credentials

        if (key.projectId !== login.projectId || !sameHost(key.host, login.host)) {
            throw new HogError(
                'setup_project_mismatch',
                `Your key is for project ${key.projectId} on ${key.host}, and this folder uses project ${login.projectId} on ${login.host}.`,
                'Unset HOG_PERSONAL_API_KEY and drop --dotenv-file, so setup uses the login for this folder.',
                EXIT_USAGE
            )
        }

        return (await this.ctx.posthog()).withoutStepUp()
    }

    products(): Promise<Product[]> {
        this.productList ??= loadProducts(this.ctx)
        return this.productList
    }

    async productsContext(): Promise<(Product & { chosen: boolean })[]> {
        const chosen = this.state?.products ?? []
        const products = chosenFirst(await this.products(), chosen)

        return products.map((product) => ({ ...product, chosen: chosen.includes(product.id) }))
    }

    async complete(step: StepId): Promise<void> {
        this.state = await updateState(this.ctx, this.scope, (current) => {
            const base = current ?? this.state
            return !base || base.completed.includes(step) ? base : { ...base, completed: [...base.completed, step] }
        })

        this.ctx.telemetry.capture('hog setup step completed', { step })
    }

    async fillLoginContext(): Promise<void> {
        const [login, loaded] = await Promise.all([this.login(), this.ctx.config()])

        this.context.host = login?.host ?? loaded?.config.host ?? this.state?.host ?? null
        this.context.projectId = login?.projectId ?? loaded?.config.projectId?.toString() ?? null
        this.context.configPath = loaded?.path ?? null
        this.context.loggedIn = login !== undefined
    }
}
