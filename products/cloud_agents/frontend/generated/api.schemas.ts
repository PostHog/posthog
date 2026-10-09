/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `1x2` - 1 vCPU, 2 GiB
 * * `2x4` - 2 vCPU, 4 GiB
 * * `2x8` - 2 vCPU, 8 GiB
 * * `4x8` - 4 vCPU, 8 GiB
 * * `4x16` - 4 vCPU, 16 GiB
 * * `8x16` - 8 vCPU, 16 GiB
 * * `8x32` - 8 vCPU, 32 GiB
 * * `16x64` - 16 vCPU, 64 GiB
 */
export type SizeNameEnumApi = (typeof SizeNameEnumApi)[keyof typeof SizeNameEnumApi]

export const SizeNameEnumApi = {
    '1x2': '1x2',
    '2x4': '2x4',
    '2x8': '2x8',
    '4x8': '4x8',
    '4x16': '4x16',
    '8x16': '8x16',
    '8x32': '8x32',
    '16x64': '16x64',
} as const

export interface CloudAgentSizeApi {
    /** Name of the size, as `<vCPU>x<memory in GiB>`.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB */
    name: SizeNameEnumApi
    /** Number of vCPUs of the sandbox. */
    vcpu: number
    /** Memory of the sandbox in GiB. */
    memory_gib: number
    /**
     * Compute price of one hour of this size in US dollars, as a decimal string.
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    price_per_hour_usd: string
}

export interface CloudAgentModelApi {
    /** ID of the model. Use it as `model` when you start a run. */
    id: string
    /** Display name of the model. */
    name: string
    /** The agent runtime that drives the model. */
    runtime_adapter: string
    /** Whether a run with no model uses this model. */
    is_default: boolean
}

/**
 * * `auto` - Auto
 * * `own_subscription` - Own Subscription
 * * `posthog` - PostHog
 */
export type InferenceModeEnumApi = (typeof InferenceModeEnumApi)[keyof typeof InferenceModeEnumApi]

export const InferenceModeEnumApi = {
    Auto: 'auto',
    OwnSubscription: 'own_subscription',
    Posthog: 'posthog',
} as const

export interface CloudAgentRateCardApi {
    /**
     * Price of one vCPU for one hour in US dollars, as a decimal string.
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    vcpu_hour_usd: string
    /**
     * Price of one GiB of memory for one hour in US dollars, as a decimal string.
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    memory_gib_hour_usd: string
    /** Version of the price list. */
    version: string
}

export interface CloudAgentLimitsApi {
    /** How many runs the project can have active at the same time. */
    max_concurrent_runs: number
    /** How many runs the project can start in one hour. */
    create_rate_per_hour: number
}

export interface CloudAgentCatalogApi {
    /** The sandbox sizes that a run can use. */
    sizes: CloudAgentSizeApi[]
    /** The models that a run can use. */
    models: CloudAgentModelApi[]
    /** The values that `inference` accepts. */
    inference_modes: InferenceModeEnumApi[]
    /** The compute prices that the size prices come from. */
    rates: CloudAgentRateCardApi
    /** The limits of this project. */
    limits: CloudAgentLimitsApi
}

export interface CloudAgentEstimateApi {
    /** The sandbox size that was priced.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB */
    size: SizeNameEnumApi
    /** How many minutes the sandbox is up. */
    minutes: number
    /**
     * Compute price of one hour of this size in US dollars, as a decimal string.
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    price_per_hour_usd: string
    /**
     * Compute cost for the given minutes in US dollars, as a decimal string. Model usage is not included.
     * @pattern ^-?\d{0,10}(?:\.\d{0,4})?$
     */
    estimate_usd: string
}

export interface CloudAgentRepositoryApi {
    /**
     * GitHub repository, in the format `owner/name`.
     * @maxLength 255
     * @pattern ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$
     */
    name: string
    /**
     * Branch that the agent starts from. Null uses the default branch of the repository.
     * @maxLength 255
     * @nullable
     */
    initial_branch?: string | null
}

/**
 * * `low` - Low
 * * `medium` - Medium
 * * `high` - High
 * * `xhigh` - Extra high
 * * `max` - Max
 * * `ultracode` - Ultracode
 */
export type CloudAgentReasoningEffortEnumApi =
    (typeof CloudAgentReasoningEffortEnumApi)[keyof typeof CloudAgentReasoningEffortEnumApi]

export const CloudAgentReasoningEffortEnumApi = {
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Xhigh: 'xhigh',
    Max: 'max',
    Ultracode: 'ultracode',
} as const

/**
 * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
 * @nullable
 */
export type CloudAgentPresetApiOutputSchema = { [key: string]: unknown } | null

/**
 * The run defaults that a preset and the project settings share. A null value sets no default.
 */
export interface CloudAgentPresetApi {
    /**
     * Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.
     * @nullable
     */
    repositories?: CloudAgentRepositoryApi[] | null
    /**
     * Default model for the agent. Null lets PostHog select the model.
     * @maxLength 100
     * @nullable
     */
    model?: string | null
    /** How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `xhigh` - Extra high
     * * `max` - Max
     * * `ultracode` - Ultracode */
    reasoning_effort?: CloudAgentReasoningEffortEnumApi | null
    /** Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB */
    size?: SizeNameEnumApi | null
    /** How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.
     *
     * * `auto` - Auto
     * * `own_subscription` - Own Subscription
     * * `posthog` - PostHog */
    inference?: InferenceModeEnumApi | null
    /**
     * Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.
     * @maxLength 20000
     * @nullable
     */
    instructions?: string | null
    /**
     * Whether the agent opens a pull request when it finishes. Null uses the product default.
     * @nullable
     */
    create_pr?: boolean | null
    /**
     * How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.
     * @minimum 1
     * @maximum 120
     * @nullable
     */
    idle_minutes?: number | null
    /**
     * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
     * @nullable
     */
    output_schema?: CloudAgentPresetApiOutputSchema
    /** ID of the preset. */
    id: string
    /** Name of the preset. */
    name: string
    /** What this preset is for. */
    description: string
    /**
     * Tags added to every run that uses this preset.
     * @maxItems 20
     * @items.maxLength 50
     */
    tags: string[]
    /**
     * ID of the user who created the preset.
     * @nullable
     */
    created_by: number | null
    /** When the preset was created. */
    created_at: string
    /** When the preset was last changed. */
    updated_at: string
}

export interface PaginatedCloudAgentPresetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CloudAgentPresetApi[]
}

/**
 * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
 * @nullable
 */
export type CloudAgentPresetCreateApiOutputSchema = { [key: string]: unknown } | null

/**
 * The run defaults that a preset and the project settings share. A null value sets no default.
 */
export interface CloudAgentPresetCreateApi {
    /**
     * Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.
     * @nullable
     */
    repositories?: CloudAgentRepositoryApi[] | null
    /**
     * Default model for the agent. Null lets PostHog select the model.
     * @maxLength 100
     * @nullable
     */
    model?: string | null
    /** How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `xhigh` - Extra high
     * * `max` - Max
     * * `ultracode` - Ultracode */
    reasoning_effort?: CloudAgentReasoningEffortEnumApi | null
    /** Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB */
    size?: SizeNameEnumApi | null
    /** How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.
     *
     * * `auto` - Auto
     * * `own_subscription` - Own Subscription
     * * `posthog` - PostHog */
    inference?: InferenceModeEnumApi | null
    /**
     * Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.
     * @maxLength 20000
     * @nullable
     */
    instructions?: string | null
    /**
     * Whether the agent opens a pull request when it finishes. Null uses the product default.
     * @nullable
     */
    create_pr?: boolean | null
    /**
     * How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.
     * @minimum 1
     * @maximum 120
     * @nullable
     */
    idle_minutes?: number | null
    /**
     * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
     * @nullable
     */
    output_schema?: CloudAgentPresetCreateApiOutputSchema
    /**
     * What this preset is for.
     * @maxLength 2000
     */
    description?: string
    /**
     * Tags added to every run that uses this preset.
     * @maxItems 20
     * @items.maxLength 50
     */
    tags?: string[]
    /**
     * Name of the preset. It is unique in the project, without regard to case.
     * @maxLength 100
     */
    name: string
}

/**
 * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
 * @nullable
 */
export type PatchedCloudAgentPresetUpdateApiOutputSchema = { [key: string]: unknown } | null

/**
 * The run defaults that a preset and the project settings share. A null value sets no default.
 */
export interface PatchedCloudAgentPresetUpdateApi {
    /**
     * Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.
     * @nullable
     */
    repositories?: CloudAgentRepositoryApi[] | null
    /**
     * Default model for the agent. Null lets PostHog select the model.
     * @maxLength 100
     * @nullable
     */
    model?: string | null
    /** How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `xhigh` - Extra high
     * * `max` - Max
     * * `ultracode` - Ultracode */
    reasoning_effort?: CloudAgentReasoningEffortEnumApi | null
    /** Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB */
    size?: SizeNameEnumApi | null
    /** How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.
     *
     * * `auto` - Auto
     * * `own_subscription` - Own Subscription
     * * `posthog` - PostHog */
    inference?: InferenceModeEnumApi | null
    /**
     * Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.
     * @maxLength 20000
     * @nullable
     */
    instructions?: string | null
    /**
     * Whether the agent opens a pull request when it finishes. Null uses the product default.
     * @nullable
     */
    create_pr?: boolean | null
    /**
     * How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.
     * @minimum 1
     * @maximum 120
     * @nullable
     */
    idle_minutes?: number | null
    /**
     * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
     * @nullable
     */
    output_schema?: PatchedCloudAgentPresetUpdateApiOutputSchema
    /**
     * What this preset is for.
     * @maxLength 2000
     */
    description?: string
    /**
     * Tags added to every run that uses this preset.
     * @maxItems 20
     * @items.maxLength 50
     */
    tags?: string[]
    /**
     * Name of the preset. It is unique in the project, without regard to case.
     * @maxLength 100
     */
    name?: string
}

/**
 * * `queued` - Queued
 * * `running` - Running
 * * `idle` - Idle
 * * `done` - Done
 */
export type CloudAgentRunStatusEnumApi = (typeof CloudAgentRunStatusEnumApi)[keyof typeof CloudAgentRunStatusEnumApi]

export const CloudAgentRunStatusEnumApi = {
    Queued: 'queued',
    Running: 'running',
    Idle: 'idle',
    Done: 'done',
} as const

/**
 * * `turn_closed` - Turn Closed
 * * `provision_failed` - Provision Failed
 * * `unexpected_failure` - Unexpected Failure
 * * `timed_out` - Timed Out
 * * `credit_spent` - Credit Spent
 * * `finished` - Finished
 * * `closed` - Closed
 * * `cancelled` - Cancelled
 */
export type CloudAgentRunStatusReasonEnumApi =
    (typeof CloudAgentRunStatusReasonEnumApi)[keyof typeof CloudAgentRunStatusReasonEnumApi]

export const CloudAgentRunStatusReasonEnumApi = {
    TurnClosed: 'turn_closed',
    ProvisionFailed: 'provision_failed',
    UnexpectedFailure: 'unexpected_failure',
    TimedOut: 'timed_out',
    CreditSpent: 'credit_spent',
    Finished: 'finished',
    Closed: 'closed',
    Cancelled: 'cancelled',
} as const

export interface CloudAgentRunPresetRefApi {
    /** ID of the preset. */
    id: string
    /** Name of the preset. */
    name: string
}

/**
 * The JSON Schema that the result of the agent must match. Null when the run has none.
 * @nullable
 */
export type CloudAgentRunConfigApiOutputSchema = { [key: string]: unknown } | null

/**
 * Reads a run: the stored configuration is in `config`, and the priced size is on the run.
 */
export interface CloudAgentRunConfigApi {
    /**
     * Model that the agent uses.
     * @nullable
     */
    model: string | null
    /** How much the model reasons before it answers. Null uses the default of the model.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `xhigh` - Extra high
     * * `max` - Max
     * * `ultracode` - Ultracode */
    reasoning_effort: CloudAgentReasoningEffortEnumApi | null
    /** Sandbox size of the run. It is fixed for the life of the run. */
    size: CloudAgentSizeApi
    /** How the run pays for model usage: `posthog` for PostHog inference, `own_subscription` for the subscription of the user.
     *
     * * `auto` - Auto
     * * `own_subscription` - Own Subscription
     * * `posthog` - PostHog */
    inference: InferenceModeEnumApi
    /** Whether the agent opens a pull request when it finishes. */
    create_pr: boolean
    /** How many minutes the sandbox waits with no activity before it stops. */
    idle_minutes: number
    /**
     * The JSON Schema that the result of the agent must match. Null when the run has none.
     * @nullable
     */
    output_schema: CloudAgentRunConfigApiOutputSchema
    /** Whether the agent got instructions from the run, its preset or the project settings. */
    readonly instructions_applied: boolean
}

/**
 * The JSON result that the agent returned for the `output_schema` of the run. Null when the run has no schema, or when the agent returned no result yet.
 * @nullable
 */
export type CloudAgentRunResultApiOutput = { [key: string]: unknown } | null

export interface CloudAgentRunResultApi {
    /**
     * URL of the pull request that the agent opened last.
     * @nullable
     */
    pr_url: string | null
    /** URLs of all pull requests that the agent opened. */
    pr_urls: string[]
    /**
     * Summary of the work, written by the agent.
     * @nullable
     */
    summary: string | null
    /**
     * The JSON result that the agent returned for the `output_schema` of the run. Null when the run has no schema, or when the agent returned no result yet.
     * @nullable
     */
    output: CloudAgentRunResultApiOutput
}

/**
 * * `billed` - Billed
 * * `unbilled` - Unbilled
 */
export type BillingModeEnumApi = (typeof BillingModeEnumApi)[keyof typeof BillingModeEnumApi]

export const BillingModeEnumApi = {
    Billed: 'billed',
    Unbilled: 'unbilled',
} as const

/**
 * * `posthog` - PostHog
 * * `own_subscription` - Own Subscription
 */
export type InferenceBillingEnumApi = (typeof InferenceBillingEnumApi)[keyof typeof InferenceBillingEnumApi]

export const InferenceBillingEnumApi = {
    Posthog: 'posthog',
    OwnSubscription: 'own_subscription',
} as const

export interface CloudAgentRunCostApi {
    /**
     * Compute cost in US dollars, as a decimal string. Null until the first sandbox reports usage.
     * @nullable
     * @pattern ^-?\d{0,10}(?:\.\d{0,4})?$
     */
    compute_usd: string | null
    /**
     * Model usage cost in US dollars, as a decimal string. Null when the run uses your own subscription, because you pay the model provider directly.
     * @nullable
     * @pattern ^-?\d{0,10}(?:\.\d{0,4})?$
     */
    inference_usd: string | null
    /**
     * Sum of the compute cost and the model usage cost, as a decimal string. Null until the compute cost is known.
     * @nullable
     * @pattern ^-?\d{0,10}(?:\.\d{0,4})?$
     */
    total_usd: string | null
    /**
     * vCPU seconds that the run used.
     * @nullable
     * @pattern ^-?\d{0,13}(?:\.\d{0,3})?$
     */
    vcpu_seconds: string | null
    /**
     * GiB seconds of memory that the run used.
     * @nullable
     * @pattern ^-?\d{0,13}(?:\.\d{0,3})?$
     */
    gib_seconds: string | null
    /** `billed` when the project pays for the run, `unbilled` when it does not.
     *
     * * `billed` - Billed
     * * `unbilled` - Unbilled */
    billing_mode: BillingModeEnumApi
    /** Who pays for the model usage of the run.
     *
     * * `posthog` - PostHog
     * * `own_subscription` - Own Subscription */
    inference_billing: InferenceBillingEnumApi | null
    /** Whether the cost is final. The cost can still change for a short time after the run stops. */
    final: boolean
}

/**
 * * `queued` - Queued
 * * `running` - Running
 * * `ended` - Ended
 */
export type CloudAgentSessionStatusEnumApi =
    (typeof CloudAgentSessionStatusEnumApi)[keyof typeof CloudAgentSessionStatusEnumApi]

export const CloudAgentSessionStatusEnumApi = {
    Queued: 'queued',
    Running: 'running',
    Ended: 'ended',
} as const

export interface CloudAgentAgentSessionApi {
    /** Position of the session in the run, from 1. */
    index: number
    /** `queued` waits for a sandbox, `running` has an agent at work, and `ended` has no sandbox.
     *
     * * `queued` - Queued
     * * `running` - Running
     * * `ended` - Ended */
    status: CloudAgentSessionStatusEnumApi
    /**
     * When the agent started work in this session.
     * @nullable
     */
    started_at: string | null
    /**
     * When the session ended.
     * @nullable
     */
    ended_at: string | null
}

export interface CloudAgentRunCreatedByApi {
    /** ID of the user. */
    id: number
    /**
     * Email address of the user.
     * @nullable
     */
    email: string | null
}

/**
 * * `api` - API
 * * `app` - App
 * * `internal` - Internal
 */
export type CallerKindEnumApi = (typeof CallerKindEnumApi)[keyof typeof CallerKindEnumApi]

export const CallerKindEnumApi = {
    Api: 'api',
    App: 'app',
    Internal: 'internal',
} as const

/**
 * Your own key and value pairs.
 */
export type CloudAgentRunApiMetadata = { [key: string]: string }

export interface CloudAgentRunApi {
    /** ID of the run. */
    id: string
    /** `queued` waits for a sandbox. `running` has an agent at work. `idle` has no sandbox, and a message continues the run. `done` is final, and a message is refused.
     *
     * * `queued` - Queued
     * * `running` - Running
     * * `idle` - Idle
     * * `done` - Done */
    status: CloudAgentRunStatusEnumApi
    /** Why the run is `idle` or `done`. Null while the run is `queued` or `running`. An `idle` run has `turn_closed` when the agent finished its turn, `timed_out`, `credit_spent`, `provision_failed` or `unexpected_failure`. A `done` run has `finished` when its pull request was merged, `closed` when every pull request was closed and not merged, or `cancelled`.
     *
     * * `turn_closed` - Turn Closed
     * * `provision_failed` - Provision Failed
     * * `unexpected_failure` - Unexpected Failure
     * * `timed_out` - Timed Out
     * * `credit_spent` - Credit Spent
     * * `finished` - Finished
     * * `closed` - Closed
     * * `cancelled` - Cancelled */
    status_reason: CloudAgentRunStatusReasonEnumApi | null
    /**
     * What the status reason means for you and what to do next. Null when there is nothing to add.
     * @nullable
     */
    status_detail: string | null
    /** When the run was created. */
    created_at: string
    /**
     * When the agent first started work.
     * @nullable
     */
    started_at: string | null
    /**
     * When the last agent session ended. Null while the run is `queued` or `running`.
     * @nullable
     */
    ended_at: string | null
    /** When the run last changed. */
    updated_at: string
    /** The task that the run started with. */
    prompt: string
    /** The repositories that the agent works in. */
    repositories: CloudAgentRepositoryApi[]
    /** The preset that the run used. Null when it used none. */
    readonly preset: CloudAgentRunPresetRefApi | null
    /** The configuration that the run uses. */
    config: CloudAgentRunConfigApi
    /** What the agent produced. */
    result: CloudAgentRunResultApi
    /** What the run cost. */
    cost: CloudAgentRunCostApi
    /** The agent sessions of the run, oldest first. A message to an `idle` run starts a new session. */
    agent_sessions: CloudAgentAgentSessionApi[]
    /**
     * Tags of the run, including the tags of its preset.
     * @maxItems 20
     * @items.maxLength 50
     */
    tags: string[]
    /** Your own key and value pairs. */
    metadata: CloudAgentRunApiMetadata
    /** The user who started the run. Null when the user no longer exists. */
    readonly created_by: CloudAgentRunCreatedByApi | null
    /** `api` for an API client, `app` for the PostHog app, `internal` for a PostHog product.
     *
     * * `api` - API
     * * `app` - App
     * * `internal` - Internal */
    caller: CallerKindEnumApi
}

export interface PaginatedCloudAgentRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CloudAgentRunApi[]
}

/**
 * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
 * @nullable
 */
export type CloudAgentRunCreateApiOutputSchema = { [key: string]: unknown } | null

/**
 * Your own key and value pairs, stored with the run and returned with it. At most 16 pairs. Keys and values are strings.
 */
export type CloudAgentRunCreateApiMetadata = { [key: string]: string }

/**
 * The run defaults that a preset and the project settings share. A null value sets no default.
 */
export interface CloudAgentRunCreateApi {
    /**
     * The repositories that the agent works in. Only one repository is supported for now. Required unless the preset or the project settings set a default.
     * @nullable
     */
    repositories?: CloudAgentRepositoryApi[] | null
    /**
     * Default model for the agent. Null lets PostHog select the model.
     * @maxLength 100
     * @nullable
     */
    model?: string | null
    /** How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `xhigh` - Extra high
     * * `max` - Max
     * * `ultracode` - Ultracode */
    reasoning_effort?: CloudAgentReasoningEffortEnumApi | null
    /** Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB */
    size?: SizeNameEnumApi | null
    /** How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.
     *
     * * `auto` - Auto
     * * `own_subscription` - Own Subscription
     * * `posthog` - PostHog */
    inference?: InferenceModeEnumApi | null
    /**
     * Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.
     * @maxLength 20000
     * @nullable
     */
    instructions?: string | null
    /**
     * Whether the agent opens a pull request when it finishes. Null uses the product default.
     * @nullable
     */
    create_pr?: boolean | null
    /**
     * How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.
     * @minimum 1
     * @maximum 120
     * @nullable
     */
    idle_minutes?: number | null
    /**
     * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
     * @nullable
     */
    output_schema?: CloudAgentRunCreateApiOutputSchema
    /**
     * The task for the agent, in plain language.
     * @maxLength 64000
     */
    prompt: string
    /**
     * ID or name of the preset whose defaults the run uses. Null uses the default preset of the project, when one is set.
     * @maxLength 100
     * @nullable
     */
    preset?: string | null
    /**
     * Tags for the run. The tags of the preset are added to them.
     * @maxItems 20
     * @items.maxLength 50
     */
    tags?: string[]
    /** Your own key and value pairs, stored with the run and returned with it. At most 16 pairs. Keys and values are strings. */
    metadata?: CloudAgentRunCreateApiMetadata
}

export type CloudAgentRunEventsApiEventsItem = { [key: string]: unknown }

export interface CloudAgentRunEventsApi {
    /** The stored events of the run, oldest first, across all agent sessions. Each event is one agent protocol message with the time it was recorded. */
    events: CloudAgentRunEventsApiEventsItem[]
    /** True when the event log is too large to return in full. The response then has the earliest agent sessions that fit. */
    truncated: boolean
}

export interface CloudAgentRunMessageApi {
    /**
     * The follow-up message for the agent, in plain language.
     * @maxLength 64000
     */
    content: string
}

export interface CloudAgentRunMessageResponseApi {
    /** True when the message started a new agent session, because the run was `idle`. False when the running agent got the message. */
    resumed: boolean
    /** The run after the message. */
    run: CloudAgentRunApi
}

export interface CloudAgentSandboxSessionUsageApi {
    /**
     * Number of vCPUs of the sandbox.
     * @pattern ^-?\d{0,5}(?:\.\d{0,3})?$
     */
    vcpu: string
    /**
     * Memory of the sandbox in GiB.
     * @pattern ^-?\d{0,5}(?:\.\d{0,3})?$
     */
    memory_gib: string
    /** When the sandbox started. */
    started_at: string
    /**
     * When the sandbox stopped. Null while it is up.
     * @nullable
     */
    ended_at: string | null
    /** How many seconds of the sandbox count for the cost. */
    seconds: number
    /**
     * Compute cost of the sandbox in US dollars, as a decimal string.
     * @pattern ^-?\d{0,10}(?:\.\d{0,4})?$
     */
    cost_usd: string
    /** Whether PostHog waived the cost of this sandbox. */
    waived: boolean
}

export interface CloudAgentRunUsageApi {
    /** ID of the run. */
    run_id: string
    /** What the run cost up to now. */
    cost: CloudAgentRunCostApi
    /** The sandboxes of the run, oldest first. */
    sessions: CloudAgentSandboxSessionUsageApi[]
}

/**
 * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
 * @nullable
 */
export type CloudAgentSettingsApiOutputSchema = { [key: string]: unknown } | null

/**
 * The run defaults that a preset and the project settings share. A null value sets no default.
 */
export interface CloudAgentSettingsApi {
    /**
     * Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.
     * @nullable
     */
    repositories?: CloudAgentRepositoryApi[] | null
    /**
     * Default model for the agent. Null lets PostHog select the model.
     * @maxLength 100
     * @nullable
     */
    model?: string | null
    /** How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `xhigh` - Extra high
     * * `max` - Max
     * * `ultracode` - Ultracode */
    reasoning_effort?: CloudAgentReasoningEffortEnumApi | null
    /** Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB */
    size?: SizeNameEnumApi | null
    /** How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.
     *
     * * `auto` - Auto
     * * `own_subscription` - Own Subscription
     * * `posthog` - PostHog */
    inference?: InferenceModeEnumApi | null
    /**
     * Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.
     * @maxLength 20000
     * @nullable
     */
    instructions?: string | null
    /**
     * Whether the agent opens a pull request when it finishes. Null uses the product default.
     * @nullable
     */
    create_pr?: boolean | null
    /**
     * How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.
     * @minimum 1
     * @maximum 120
     * @nullable
     */
    idle_minutes?: number | null
    /**
     * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
     * @nullable
     */
    output_schema?: CloudAgentSettingsApiOutputSchema
    /**
     * ID of the preset that a run uses when it names no preset.
     * @nullable
     */
    default_preset: string | null
    /** How many runs the project can have active at the same time. */
    max_concurrent_runs: number
    /** How many runs the project can start in one hour. */
    create_rate_per_hour: number
    /**
     * When the settings were last changed.
     * @nullable
     */
    updated_at: string | null
}

/**
 * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
 * @nullable
 */
export type PatchedCloudAgentSettingsUpdateApiOutputSchema = { [key: string]: unknown } | null

/**
 * The run defaults that a preset and the project settings share. A null value sets no default.
 */
export interface PatchedCloudAgentSettingsUpdateApi {
    /**
     * Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.
     * @nullable
     */
    repositories?: CloudAgentRepositoryApi[] | null
    /**
     * Default model for the agent. Null lets PostHog select the model.
     * @maxLength 100
     * @nullable
     */
    model?: string | null
    /** How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `xhigh` - Extra high
     * * `max` - Max
     * * `ultracode` - Ultracode */
    reasoning_effort?: CloudAgentReasoningEffortEnumApi | null
    /** Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB */
    size?: SizeNameEnumApi | null
    /** How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.
     *
     * * `auto` - Auto
     * * `own_subscription` - Own Subscription
     * * `posthog` - PostHog */
    inference?: InferenceModeEnumApi | null
    /**
     * Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.
     * @maxLength 20000
     * @nullable
     */
    instructions?: string | null
    /**
     * Whether the agent opens a pull request when it finishes. Null uses the product default.
     * @nullable
     */
    create_pr?: boolean | null
    /**
     * How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.
     * @minimum 1
     * @maximum 120
     * @nullable
     */
    idle_minutes?: number | null
    /**
     * A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.
     * @nullable
     */
    output_schema?: PatchedCloudAgentSettingsUpdateApiOutputSchema
    /**
     * ID of the preset that a run uses when it names no preset. Null sets no default preset.
     * @nullable
     */
    default_preset?: string | null
}

/**
 * * `day` - Day
 * * `preset` - Preset
 */
export type UsageGroupByEnumApi = (typeof UsageGroupByEnumApi)[keyof typeof UsageGroupByEnumApi]

export const UsageGroupByEnumApi = {
    Day: 'day',
    Preset: 'preset',
} as const

export interface CloudAgentUsageTotalsApi {
    /** Number of runs. */
    runs: number
    /**
     * Compute cost in US dollars, as a decimal string.
     * @pattern ^-?\d{0,10}(?:\.\d{0,4})?$
     */
    compute_usd: string
    /**
     * Model usage cost in US dollars, as a decimal string. Runs on your own subscription add nothing.
     * @pattern ^-?\d{0,10}(?:\.\d{0,4})?$
     */
    inference_usd: string
    /**
     * Sum of the compute cost and the model usage cost, as a decimal string.
     * @pattern ^-?\d{0,10}(?:\.\d{0,4})?$
     */
    total_usd: string
    /**
     * vCPU seconds used.
     * @pattern ^-?\d{0,13}(?:\.\d{0,3})?$
     */
    vcpu_seconds: string
    /**
     * GiB seconds of memory used.
     * @pattern ^-?\d{0,13}(?:\.\d{0,3})?$
     */
    gib_seconds: string
}

export interface CloudAgentUsageBucketApi {
    /**
     * The UTC date of the bucket for `group_by=day`. The preset ID for `group_by=preset`, or null for the runs that used no preset.
     * @nullable
     */
    key: string | null
    /**
     * Name of the preset for `group_by=preset`. Null for other buckets.
     * @nullable
     */
    name: string | null
    /** Usage of the runs in this bucket. */
    usage: CloudAgentUsageTotalsApi
}

export interface CloudAgentUsageSummaryApi {
    /** Start of the range. */
    date_from: string
    /** End of the range, not included. */
    date_to: string
    /** How the buckets are grouped.
     *
     * * `day` - Day
     * * `preset` - Preset */
    group_by: UsageGroupByEnumApi
    /** Usage of all runs created in the range. */
    totals: CloudAgentUsageTotalsApi
    /** Usage for each day or for each preset. */
    buckets: CloudAgentUsageBucketApi[]
}

export type CloudAgentsEstimateRetrieveParams = {
    /**
     * How many minutes the sandbox is up.
     * @minimum 1
     * @maximum 1440
     */
    minutes: number
    /**
     * Sandbox size to price, as `<vCPU>x<memory in GiB>`.
     *
     * * `1x2` - 1 vCPU, 2 GiB
     * * `2x4` - 2 vCPU, 4 GiB
     * * `2x8` - 2 vCPU, 8 GiB
     * * `4x8` - 4 vCPU, 8 GiB
     * * `4x16` - 4 vCPU, 16 GiB
     * * `8x16` - 8 vCPU, 16 GiB
     * * `8x32` - 8 vCPU, 32 GiB
     * * `16x64` - 16 vCPU, 64 GiB
     * @minLength 1
     */
    size: CloudAgentsEstimateRetrieveSize
}

export type CloudAgentsEstimateRetrieveSize =
    (typeof CloudAgentsEstimateRetrieveSize)[keyof typeof CloudAgentsEstimateRetrieveSize]

export const CloudAgentsEstimateRetrieveSize = {
    '1x2': '1x2',
    '2x4': '2x4',
    '2x8': '2x8',
    '4x8': '4x8',
    '4x16': '4x16',
    '8x16': '8x16',
    '8x32': '8x32',
    '16x64': '16x64',
} as const

export type CloudAgentsPresetsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CloudAgentsRunsListParams = {
    /**
     * Return only the runs created at or after this time, in ISO 8601 format.
     */
    created_after?: string
    /**
     * Return only the runs created before this time, in ISO 8601 format.
     */
    created_before?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Return only the runs that used this preset.
     */
    preset_id?: string
    /**
     * Return runs whose repository contains this text.
     * @minLength 1
     * @maxLength 255
     */
    repository?: string
    /**
     * Return only the runs with this status. A status filter covers the newest 1,000 runs that are active, for `queued` and `running`, or that have no agent at work, for `idle` and `done`.
     *
     * * `queued` - Queued
     * * `running` - Running
     * * `idle` - Idle
     * * `done` - Done
     * @minLength 1
     */
    status?: CloudAgentsRunsListStatus
    /**
     * Return only the runs that have this tag.
     * @minLength 1
     * @maxLength 50
     */
    tag?: string
}

export type CloudAgentsRunsListStatus = (typeof CloudAgentsRunsListStatus)[keyof typeof CloudAgentsRunsListStatus]

export const CloudAgentsRunsListStatus = {
    Queued: 'queued',
    Running: 'running',
    Idle: 'idle',
    Done: 'done',
} as const

export type CloudAgentsRunsEventsRetrieveParams = {
    /**
     * `json` returns the stored events as one JSON object. This is the default.
     */
    format?: CloudAgentsRunsEventsRetrieveFormat
    /**
     * Applies to the stream only: `latest` skips the stored events and sends only new events.
     */
    start?: CloudAgentsRunsEventsRetrieveStart
}

export type CloudAgentsRunsEventsRetrieveFormat =
    (typeof CloudAgentsRunsEventsRetrieveFormat)[keyof typeof CloudAgentsRunsEventsRetrieveFormat]

export const CloudAgentsRunsEventsRetrieveFormat = {
    Json: 'json',
} as const

export type CloudAgentsRunsEventsRetrieveStart =
    (typeof CloudAgentsRunsEventsRetrieveStart)[keyof typeof CloudAgentsRunsEventsRetrieveStart]

export const CloudAgentsRunsEventsRetrieveStart = {
    Latest: 'latest',
} as const

export type CloudAgentsUsageRetrieveParams = {
    /**
     * Start of the range, in ISO 8601 format. The default is 30 days before `date_to`.
     */
    date_from?: string
    /**
     * End of the range, not included, in ISO 8601 format. The default is now.
     */
    date_to?: string
    /**
     * `day` gives one bucket for each UTC day. `preset` gives one bucket for each preset.
     *
     * * `day` - Day
     * * `preset` - Preset
     * @minLength 1
     */
    group_by?: CloudAgentsUsageRetrieveGroupBy
}

export type CloudAgentsUsageRetrieveGroupBy =
    (typeof CloudAgentsUsageRetrieveGroupBy)[keyof typeof CloudAgentsUsageRetrieveGroupBy]

export const CloudAgentsUsageRetrieveGroupBy = {
    Day: 'day',
    Preset: 'preset',
} as const
