/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface BetsNextActionApi {
    /** Stable identifier. */
    id: string
    /** Bet requiring attention. */
    bet_id: string
    /** Name of the bet. */
    bet_title: string
    /** What needs attention. */
    title: string
    /** What to do next. */
    description: string
    /** Why this needs attention. */
    label: string
    /**
     * Related work item.
     * @nullable
     */
    work_id: string | null
    /** Pull request or other place to act. */
    url: string
}

export interface BetsOwnerApi {
    /** User who owns the bet. */
    user_id: number
    /** Display name. */
    name: string
    /** Email address. */
    email: string
}

/**
 * * `increase` - Increase
 * * `decrease` - Decrease
 */
export type BetDirectionEnumApi = (typeof BetDirectionEnumApi)[keyof typeof BetDirectionEnumApi]

export const BetDirectionEnumApi = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

export interface BetsSecondaryMetricApi {
    /**
     * Saved PostHog insight used as a guardrail.
     * @maxLength 32
     */
    insight: string
    /**
     * Name of the guardrail metric.
     * @maxLength 255
     */
    name: string
    /** Whether higher or lower is better.
     *
     * * `increase` - Increase
     * * `decrease` - Decrease */
    direction?: BetDirectionEnumApi
    /**
     * Largest tolerated relative regression, 0.05 for 5%.
     * @minimum 0
     * @maximum 1
     */
    max_regression?: number
}

/**
 * * `setting_up` - Setting up
 * * `running` - Running
 * * `paused` - Paused
 * * `reached` - Goal reached
 * * `spent` - Budget used
 * * `closed` - Closed
 */
export type BetStatusEnumApi = (typeof BetStatusEnumApi)[keyof typeof BetStatusEnumApi]

export const BetStatusEnumApi = {
    SettingUp: 'setting_up',
    Running: 'running',
    Paused: 'paused',
    Reached: 'reached',
    Spent: 'spent',
    Closed: 'closed',
} as const

export interface BetsMoneyApi {
    /** Allocated budget in USD cents. */
    allocated_cents: number
    /** Settled spend in USD cents. */
    spent_cents: number
    /** Budget held for running work in USD cents. */
    reserved_cents: number
    /** Uncommitted budget in USD cents. */
    available_cents: number
}

export interface BetsMetricApi {
    /** Metric name. */
    name: string
    /** Display unit from the saved insight. */
    unit: string
    /** Values in chronological order. */
    values: number[]
    /** Dates corresponding to values. */
    dates: string[]
    /**
     * Latest available value.
     * @nullable
     */
    current: number | null
    /**
     * Percentage change across the displayed period.
     * @nullable
     */
    change: number | null
    /** Reason a measurement is unavailable. */
    message: string
}

/**
 * * `setting_up` - Setting up
 * * `checking_measure` - Checking the measure
 * * `finding_ideas` - Finding ideas
 * * `checking_ideas` - Checking ideas
 * * `choosing` - Choosing
 * * `building` - Building
 * * `reviewing` - Reviewing
 * * `testing` - Testing
 * * `confirming_goal` - Confirming the goal
 * * `waiting` - Waiting
 * * `paused` - Paused
 * * `ended` - Ended
 */
export type BetPhaseEnumApi = (typeof BetPhaseEnumApi)[keyof typeof BetPhaseEnumApi]

export const BetPhaseEnumApi = {
    SettingUp: 'setting_up',
    CheckingMeasure: 'checking_measure',
    FindingIdeas: 'finding_ideas',
    CheckingIdeas: 'checking_ideas',
    Choosing: 'choosing',
    Building: 'building',
    Reviewing: 'reviewing',
    Testing: 'testing',
    ConfirmingGoal: 'confirming_goal',
    Waiting: 'waiting',
    Paused: 'paused',
    Ended: 'ended',
} as const

/**
 * * `tracking` - Tracking
 * * `measure` - Measure
 * * `scout` - Scout
 * * `idea` - Idea
 * * `experiment` - Experiment
 * * `pull_request` - Pull request
 * * `problem` - Problem
 * * `idle` - Idle
 * * `paused` - Paused
 * * `reached` - Reached
 * * `ended` - Ended
 */
export type BetTileEnumApi = (typeof BetTileEnumApi)[keyof typeof BetTileEnumApi]

export const BetTileEnumApi = {
    Tracking: 'tracking',
    Measure: 'measure',
    Scout: 'scout',
    Idea: 'idea',
    Experiment: 'experiment',
    PullRequest: 'pull_request',
    Problem: 'problem',
    Idle: 'idle',
    Paused: 'paused',
    Reached: 'reached',
    Ended: 'ended',
} as const

/**
 * * `ideas` - Ideas
 * * `edit` - Edit
 * * `pull_request` - Pull request
 * * `work` - Work
 * * `budget` - Budget
 * * `settings` - Settings
 */
export type BetActionKindEnumApi = (typeof BetActionKindEnumApi)[keyof typeof BetActionKindEnumApi]

export const BetActionKindEnumApi = {
    Ideas: 'ideas',
    Edit: 'edit',
    PullRequest: 'pull_request',
    Work: 'work',
    Budget: 'budget',
    Settings: 'settings',
} as const

/**
 * * `retry` - Retry
 * * `drop` - Drop
 * * `build` - Build
 * * `dismiss` - Dismiss
 * * `extend` - Extend
 */
export type BetWorkActionEnumApi = (typeof BetWorkActionEnumApi)[keyof typeof BetWorkActionEnumApi]

export const BetWorkActionEnumApi = {
    Retry: 'retry',
    Drop: 'drop',
    Build: 'build',
    Dismiss: 'dismiss',
    Extend: 'extend',
} as const

export interface BetsStateActionApi {
    /** Button text. */
    label: string
    /** What the button opens or does.
     *
     * * `ideas` - Ideas
     * * `edit` - Edit
     * * `pull_request` - Pull request
     * * `work` - Work
     * * `budget` - Budget
     * * `settings` - Settings */
    kind: BetActionKindEnumApi
    /** Whether the owner must act, rather than an optional step. */
    primary: boolean
    /**
     * Work item the button opens or acts on.
     * @nullable
     */
    work_id: string | null
    /** Work action the button runs on the work item, or empty to open it.
     *
     * * `retry` - Retry
     * * `drop` - Drop
     * * `build` - Build
     * * `dismiss` - Dismiss
     * * `extend` - Extend */
    work_action: BetWorkActionEnumApi | null
    /** Pull request to open. */
    url: string
}

export interface BetsScoutStateApi {
    /** What the Scout does now, in a few words. */
    label: string
    /** Why the Scout does this, in one or two sentences. */
    reason: string
}

export interface BetsStateApi {
    /** What the bet is doing now.
     *
     * * `setting_up` - Setting up
     * * `checking_measure` - Checking the measure
     * * `finding_ideas` - Finding ideas
     * * `checking_ideas` - Checking ideas
     * * `choosing` - Choosing
     * * `building` - Building
     * * `reviewing` - Reviewing
     * * `testing` - Testing
     * * `confirming_goal` - Confirming the goal
     * * `waiting` - Waiting
     * * `paused` - Paused
     * * `ended` - Ended */
    phase: BetPhaseEnumApi
    /** Which part of Bets the status line is about.
     *
     * * `tracking` - Tracking
     * * `measure` - Measure
     * * `scout` - Scout
     * * `idea` - Idea
     * * `experiment` - Experiment
     * * `pull_request` - Pull request
     * * `problem` - Problem
     * * `idle` - Idle
     * * `paused` - Paused
     * * `reached` - Reached
     * * `ended` - Ended */
    tile: BetTileEnumApi
    /** Main status line. */
    headline: string
    /** Second status line. */
    detail: string
    /** Title of the idea the status line is about. */
    subject: string
    /**
     * Work item the status line is about.
     * @nullable
     */
    work_id: string | null
    /** Whether Bets works on this step now. */
    working: boolean
    /** The owner's next step for this status. */
    action: BetsStateActionApi | null
    /** A second choice next to the action. */
    alternative: BetsStateActionApi | null
    /** What the Scout does now. */
    scout: BetsScoutStateApi
    /** Ideas ready for the owner to choose. */
    ready_ideas: number
    /** Owner ideas that wait for the Scout's check. */
    checking_ideas: number
    /** Why no idea can be built now, or empty. */
    build_blocked: string
    /** Whether the bet takes new owner ideas. */
    can_add_idea: boolean
    /** Whether the bet waits for the owner. */
    needs_you: boolean
    /** Everything the owner must do, most urgent first. */
    actions: BetsNextActionApi[]
}

export interface BetsEntryApi {
    /** The person who owns and controls this bet. */
    owner: BetsOwnerApi
    /** Bet ID. */
    id: string
    /** Human-readable bet number. */
    reference: number
    /** Bet name. */
    title: string
    /** What we believe and why. */
    statement: string
    /** Intended audience. */
    audience: string
    /** Product area. */
    area: string
    /** Main connected repository. */
    repository: string
    /** Connected repositories. The first is the main one. */
    repositories: string[]
    /** Primary metric insight. */
    goal_insight: string
    /** How the owner described the goal measure, when they wrote it in words. */
    goal_description: string
    /** Primary metric name. */
    goal_metric: string
    /** Guardrails. */
    secondary_metrics: BetsSecondaryMetricApi[]
    /**
     * Primary metric target, empty until set.
     * @nullable
     * @pattern ^-?\d{0,16}(?:\.\d{0,4})?$
     */
    target: string | null
    /** Whether higher or lower is better.
     *
     * * `increase` - Increase
     * * `decrease` - Decrease */
    direction: BetDirectionEnumApi
    /** Primary metric unit. */
    unit: string
    /** Bet lifecycle state.
     *
     * * `setting_up` - Setting up
     * * `running` - Running
     * * `paused` - Paused
     * * `reached` - Goal reached
     * * `spent` - Budget used
     * * `closed` - Closed */
    status: BetStatusEnumApi
    /**
     * Primary metric when the bet started running.
     * @nullable
     */
    baseline_value: number | null
    /**
     * When the baseline was recorded.
     * @nullable
     */
    baseline_at: string | null
    /** Budget accounting. */
    money: BetsMoneyApi
    /** Primary metric history. */
    metric: BetsMetricApi
    /** Some task usage is still settling. */
    spend_pending: boolean
    /** Ideas measured to a conclusion. */
    ideas_tried: number
    /** Ideas that improved the primary metric. */
    ideas_won: number
    /** Whether the bet waits for the owner, for example to choose an idea. */
    needs_you: boolean
    /** What the bet does now and what it needs from the owner. */
    state: BetsStateApi
    /** Latest change. */
    updated_at: string
}

/**
 * * `scout` - Scout
 * * `tracking` - Tracking
 * * `idea` - Idea
 */
export type ModelStepEnumApi = (typeof ModelStepEnumApi)[keyof typeof ModelStepEnumApi]

export const ModelStepEnumApi = {
    Scout: 'scout',
    Tracking: 'tracking',
    Idea: 'idea',
} as const

/**
 * * `credits` - PostHog credits
 * * `subscription` - ChatGPT plan
 */
export type StepBillingEnumApi = (typeof StepBillingEnumApi)[keyof typeof StepBillingEnumApi]

export const StepBillingEnumApi = {
    Credits: 'credits',
    Subscription: 'subscription',
} as const

export interface BetsStepModelApi {
    /** Which step uses this model.
     *
     * * `scout` - Scout
     * * `tracking` - Tracking
     * * `idea` - Idea */
    step: ModelStepEnumApi
    /** Model ID, or empty for the project default. */
    model: string
    /** Reasoning effort, or empty for the default. */
    reasoning_effort: string
    /** Who pays for this step's model use.
     *
     * * `credits` - PostHog credits
     * * `subscription` - ChatGPT plan */
    billing: StepBillingEnumApi
    /** Display name of the model. */
    model_label: string
}

export interface BetsModelOptionApi {
    /** Model ID. */
    model: string
    /** Display name. */
    label: string
    /** Runtime that drives the model. */
    runtime_adapter: string
    /** Reasoning efforts it supports. */
    supported_efforts: string[]
    /**
     * Cost compared with the baseline model.
     * @nullable
     */
    cost_multiplier: string | null
}

export interface BetsSettingsApi {
    /** Project budget in USD cents. */
    budget_cents: number
    /** Saved insight for the project North Star. */
    north_star_insight: string
    /** Model and billing for each step. */
    models: BetsStepModelApi[]
    /** Models a step may use. */
    model_options: BetsModelOptionApi[]
    /** Whether a connected ChatGPT plan can pay for unattended runs. */
    plan_available: boolean
    /** Shortest experiment run in hours. Zero lets the plan decide. */
    min_run_hours: number
    /** Smallest relative change, in percent, an experiment plans to find. */
    mde_percent: number
    /** Hours the goal metric must stay at the target before the bet counts as reached. */
    goal_confirm_hours: number
}

export interface BetsOverviewApi {
    /** Everything that needs attention, most urgent first. */
    next_actions: BetsNextActionApi[]
    /** Bets in this project. */
    bets: BetsEntryApi[]
    /** Current project North Star. */
    north_star: BetsMetricApi
    /** Project budget, North Star and models. */
    settings: BetsSettingsApi
    /** Total allocated project budget. */
    allocated_cents: number
    /** Project budget still available. */
    unallocated_cents: number
    /** Whether the viewer can create or change bets. */
    can_edit: boolean
}

export interface BetsWriteApi {
    /** Stable ID for retrying creation without duplicates. */
    operation_id?: string
    /**
     * Short name of the bet.
     * @maxLength 160
     */
    title: string
    /**
     * What you believe will improve and why.
     * @maxLength 10000
     */
    statement: string
    /**
     * People this bet aims to help.
     * @maxLength 500
     */
    audience?: string
    /**
     * Product area for filtering.
     * @maxLength 120
     */
    area?: string
    /**
     * Main GitHub repository in owner/repository form. Defaults to the first of repositories.
     * @maxLength 255
     * @pattern ^[\w.-]+/[\w.-]+$
     */
    repository?: string
    /**
     * GitHub repositories Bets reads and changes, in owner/repository form. The first is the main one.
     * @maxItems 10
     * @items.maxLength 255
     * @items.pattern ^[\w.-]+/[\w.-]+$
     */
    repositories?: string[]
    /**
     * Saved insight with one series that measures the goal. Leave empty and describe the goal instead.
     * @maxLength 32
     */
    goal_insight?: string
    /**
     * How to measure the goal, in words, when no saved insight fits. Bets finds or creates the insight.
     * @maxLength 2000
     */
    goal_description?: string
    /**
     * Name of the primary metric.
     * @maxLength 255
     */
    goal_metric: string
    /**
     * The owner's own ideas. The Scout checks each one against the data before anyone chooses.
     * @maxItems 5
     * @items.maxLength 255
     */
    ideas?: string[]
    /** Guardrails that must not get worse. */
    secondary_metrics?: BetsSecondaryMetricApi[]
    /**
     * Target value of the primary metric. Set it after Bets finds the insight for a described goal.
     * @nullable
     * @pattern ^-?\d{0,16}(?:\.\d{0,4})?$
     */
    target?: string | null
    /** Whether higher or lower is better.
     *
     * * `increase` - Increase
     * * `decrease` - Decrease */
    direction?: BetDirectionEnumApi
    /**
     * Display unit, for example %.
     * @maxLength 32
     */
    unit?: string
    /**
     * Budget for this bet in USD cents.
     * @minimum 0
     * @maximum 1000000000
     */
    budget_cents: number
}

export interface BetsSpendPointApi {
    /** When this usage settled. */
    at: string
    /** Total settled spend up to this time, in USD cents. */
    spent_cents: number
}

/**
 * * `tracking` - Tracking
 * * `idea` - Idea
 * * `cleanup` - Cleanup
 */
export type WorkKindEnumApi = (typeof WorkKindEnumApi)[keyof typeof WorkKindEnumApi]

export const WorkKindEnumApi = {
    Tracking: 'tracking',
    Idea: 'idea',
    Cleanup: 'cleanup',
} as const

/**
 * * `proposed` - Proposed
 * * `dismissed` - Dismissed
 * * `working` - Working
 * * `review` - In review
 * * `live` - Live
 * * `done` - Done
 * * `dropped` - Dropped
 * * `stuck` - Stuck
 */
export type WorkStageEnumApi = (typeof WorkStageEnumApi)[keyof typeof WorkStageEnumApi]

export const WorkStageEnumApi = {
    Proposed: 'proposed',
    Dismissed: 'dismissed',
    Working: 'working',
    Review: 'review',
    Live: 'live',
    Done: 'done',
    Dropped: 'dropped',
    Stuck: 'stuck',
} as const

/**
 * * `won` - Won
 * * `lost` - Lost
 * * `flat` - No clear effect
 * * `harmed` - Guardrail regression
 * * `dropped` - Dropped
 */
export type IdeaOutcomeEnumApi = (typeof IdeaOutcomeEnumApi)[keyof typeof IdeaOutcomeEnumApi]

export const IdeaOutcomeEnumApi = {
    Won: 'won',
    Lost: 'lost',
    Flat: 'flat',
    Harmed: 'harmed',
    Dropped: 'dropped',
} as const

/**
 * People exposed per variant.
 */
export type BetsIdeaResultApiExposures = { [key: string]: number }

/**
 * Relative effect interval on the primary metric per test variant.
 */
export type BetsIdeaResultApiPrimary = { [key: string]: number[] | null }

export interface BetsIdeaResultApi {
    /** How the idea ended.
     *
     * * `won` - Won
     * * `lost` - Lost
     * * `flat` - No clear effect
     * * `harmed` - Guardrail regression
     * * `dropped` - Dropped */
    outcome?: IdeaOutcomeEnumApi
    /** Variant kept when the experiment ended. */
    variant?: string
    /** Why the experiment ended this way. */
    verdict?: string
    /** People exposed per variant. */
    exposures?: BetsIdeaResultApiExposures
    /** Relative effect interval on the primary metric per test variant. */
    primary?: BetsIdeaResultApiPrimary
    /** People in the smallest group. */
    smallest_sample?: number
    /** Guardrails that got worse. */
    harmed_guardrails?: string[]
    /** What we learned. */
    summary?: string
}

/**
 * * `scout` - Scout
 * * `owner` - Owner
 */
export type IdeaSourceEnumApi = (typeof IdeaSourceEnumApi)[keyof typeof IdeaSourceEnumApi]

export const IdeaSourceEnumApi = {
    Scout: 'scout',
    Owner: 'owner',
} as const

/**
 * * `` - None
 * * `pending` - Pending
 * * `supported` - Supported
 * * `not_supported` - Not supported
 */
export type IdeaAssessmentEnumApi = (typeof IdeaAssessmentEnumApi)[keyof typeof IdeaAssessmentEnumApi]

export const IdeaAssessmentEnumApi = {
    Pending: 'pending',
    Supported: 'supported',
    NotSupported: 'not_supported',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * * `replay` - Session replay
 * * `insight` - Insight
 * * `chart` - Chart
 * * `experiment` - Experiment
 * * `error` - Error
 * * `link` - Link
 */
export type EvidenceKindEnumApi = (typeof EvidenceKindEnumApi)[keyof typeof EvidenceKindEnumApi]

export const EvidenceKindEnumApi = {
    Replay: 'replay',
    Insight: 'insight',
    Chart: 'chart',
    Experiment: 'experiment',
    Error: 'error',
    Link: 'link',
} as const

export interface BetsEvidenceApi {
    /** What the evidence link points to.
     *
     * * `replay` - Session replay
     * * `insight` - Insight
     * * `chart` - Chart
     * * `experiment` - Experiment
     * * `error` - Error
     * * `link` - Link */
    kind: EvidenceKindEnumApi
    /** Short text that describes the evidence. */
    label: string
    /** Link to the PostHog data, or chart:<id> for a chart in the report. */
    url: string
}

export interface BetsPlanApi {
    /**
     * Days the experiment runs before Bets reads the result.
     * @nullable
     */
    days: number | null
    /**
     * Smallest relative change, in percent, the run can find.
     * @nullable
     */
    mde: number | null
    /**
     * People a day who see the change.
     * @nullable
     */
    audience: number | null
    /** Whether the metric has a weekly pattern. */
    weekly: boolean
    /** Whether the plan is longer than four weeks. */
    too_long: boolean
    /**
     * Mean of the goal metric used for the plan.
     * @nullable
     */
    mean: number | null
    /**
     * Variance of the goal metric used for the plan.
     * @nullable
     */
    variance: number | null
    /**
     * New length after the re-plan, waiting for the owner to extend or stop.
     * @nullable
     */
    proposed_days: number | null
    /** Whether the owner approved this plan. */
    approved: boolean
    /** Whether Bets re-planned from the control group. */
    replanned: boolean
}

export const BetsWorkApiAssessment = { ...IdeaAssessmentEnumApi, ...BlankEnumApi } as const
export interface BetsWorkApi {
    /** Work item ID. */
    id: string
    /** Goal revision this work belongs to. */
    goal_version: number
    /** Tracking check or idea.
     *
     * * `tracking` - Tracking
     * * `idea` - Idea
     * * `cleanup` - Cleanup */
    kind: WorkKindEnumApi
    /** Where this work is in its lifecycle.
     *
     * * `proposed` - Proposed
     * * `dismissed` - Dismissed
     * * `working` - Working
     * * `review` - In review
     * * `live` - Live
     * * `done` - Done
     * * `dropped` - Dropped
     * * `stuck` - Stuck */
    stage: WorkStageEnumApi
    /** Work title. */
    title: string
    /** The idea's evidence and proposed change. */
    summary: string
    /** Latest status in plain language. */
    note: string
    /** Pull request opened by the task. */
    pr_url: string
    /** Pull request state from Tasks. */
    pr_state: string
    /** Feature flag the change ships behind. */
    flag_key: string
    /**
     * Native experiment measuring the idea.
     * @nullable
     */
    experiment_id: number | null
    /** Measured outcome, effect intervals, exposures and verdict. */
    result: BetsIdeaResultApi
    /**
     * Native task doing the work.
     * @nullable
     */
    task_id: string | null
    /** Latest native task run status. */
    task_status: string
    /** Task runs started for this work. */
    attempts: number
    /** Settled cost in USD cents. */
    spent_cents: number
    /** When the work started. */
    created_at: string
    /**
     * When the work finished.
     * @nullable
     */
    finished_at: string | null
    /** Who proposed the idea.
     *
     * * `scout` - Scout
     * * `owner` - Owner */
    source: IdeaSourceEnumApi
    /** The Scout's check of the idea against the data.
     *
     * * `` - None
     * * `pending` - Pending
     * * `supported` - Supported
     * * `not_supported` - Not supported */
    assessment: (typeof BetsWorkApiAssessment)[keyof typeof BetsWorkApiAssessment]
    /** Links to the PostHog data behind the idea. */
    evidence: BetsEvidenceApi[]
    /**
     * Scout report that describes the idea.
     * @nullable
     */
    report_id: string | null
    /** Why the owner dismissed the idea. */
    dismissed_reason: string
    /** The metric the Scout expects this idea to move. */
    moves_metric: string
    /** Experiment plan for an idea. */
    plan: BetsPlanApi
}

export interface BetsScoutApi {
    /** Native Scout configuration. */
    config_id: string
    /** Native Scout name. */
    name: string
    /** Whether the Scout may run. */
    enabled: boolean
    /** Whether the Scout is searching for an idea right now. */
    running: boolean
}

export interface BetsDetailApi {
    /** The person who owns and controls this bet. */
    owner: BetsOwnerApi
    /** Bet ID. */
    id: string
    /** Human-readable bet number. */
    reference: number
    /** Bet name. */
    title: string
    /** What we believe and why. */
    statement: string
    /** Intended audience. */
    audience: string
    /** Product area. */
    area: string
    /** Main connected repository. */
    repository: string
    /** Connected repositories. The first is the main one. */
    repositories: string[]
    /** Primary metric insight. */
    goal_insight: string
    /** How the owner described the goal measure, when they wrote it in words. */
    goal_description: string
    /** Primary metric name. */
    goal_metric: string
    /** Guardrails. */
    secondary_metrics: BetsSecondaryMetricApi[]
    /**
     * Primary metric target, empty until set.
     * @nullable
     * @pattern ^-?\d{0,16}(?:\.\d{0,4})?$
     */
    target: string | null
    /** Whether higher or lower is better.
     *
     * * `increase` - Increase
     * * `decrease` - Decrease */
    direction: BetDirectionEnumApi
    /** Primary metric unit. */
    unit: string
    /** Bet lifecycle state.
     *
     * * `setting_up` - Setting up
     * * `running` - Running
     * * `paused` - Paused
     * * `reached` - Goal reached
     * * `spent` - Budget used
     * * `closed` - Closed */
    status: BetStatusEnumApi
    /**
     * Primary metric when the bet started running.
     * @nullable
     */
    baseline_value: number | null
    /**
     * When the baseline was recorded.
     * @nullable
     */
    baseline_at: string | null
    /** Budget accounting. */
    money: BetsMoneyApi
    /** Primary metric history. */
    metric: BetsMetricApi
    /** Some task usage is still settling. */
    spend_pending: boolean
    /** Ideas measured to a conclusion. */
    ideas_tried: number
    /** Ideas that improved the primary metric. */
    ideas_won: number
    /** Whether the bet waits for the owner, for example to choose an idea. */
    needs_you: boolean
    /** What the bet does now and what it needs from the owner. */
    state: BetsStateApi
    /** Latest change. */
    updated_at: string
    /** Whether the viewer owns this bet and can change it. */
    is_owner: boolean
    /** Cumulative settled spend over time. */
    spend_history: BetsSpendPointApi[]
    /** Current goal revision. */
    goal_version: number
    /**
     * When the goal metric reached the target; the bet counts as reached after the confirm time.
     * @nullable
     */
    goal_met_since: string | null
    /** Tracking checks and ideas, newest first. */
    work: BetsWorkApi[]
    /** Current guardrail readings. */
    secondary_values: BetsMetricApi[]
    /** The Scout looking for ideas. */
    scout: BetsScoutApi | null
    /** The most urgent next step. */
    next_action: BetsNextActionApi | null
    /** Whether the viewer can change this bet. */
    can_edit: boolean
}

export interface PatchedBetsWriteApi {
    /** Stable ID for retrying creation without duplicates. */
    operation_id?: string
    /**
     * Short name of the bet.
     * @maxLength 160
     */
    title?: string
    /**
     * What you believe will improve and why.
     * @maxLength 10000
     */
    statement?: string
    /**
     * People this bet aims to help.
     * @maxLength 500
     */
    audience?: string
    /**
     * Product area for filtering.
     * @maxLength 120
     */
    area?: string
    /**
     * Main GitHub repository in owner/repository form. Defaults to the first of repositories.
     * @maxLength 255
     * @pattern ^[\w.-]+/[\w.-]+$
     */
    repository?: string
    /**
     * GitHub repositories Bets reads and changes, in owner/repository form. The first is the main one.
     * @maxItems 10
     * @items.maxLength 255
     * @items.pattern ^[\w.-]+/[\w.-]+$
     */
    repositories?: string[]
    /**
     * Saved insight with one series that measures the goal. Leave empty and describe the goal instead.
     * @maxLength 32
     */
    goal_insight?: string
    /**
     * How to measure the goal, in words, when no saved insight fits. Bets finds or creates the insight.
     * @maxLength 2000
     */
    goal_description?: string
    /**
     * Name of the primary metric.
     * @maxLength 255
     */
    goal_metric?: string
    /**
     * The owner's own ideas. The Scout checks each one against the data before anyone chooses.
     * @maxItems 5
     * @items.maxLength 255
     */
    ideas?: string[]
    /** Guardrails that must not get worse. */
    secondary_metrics?: BetsSecondaryMetricApi[]
    /**
     * Target value of the primary metric. Set it after Bets finds the insight for a described goal.
     * @nullable
     * @pattern ^-?\d{0,16}(?:\.\d{0,4})?$
     */
    target?: string | null
    /** Whether higher or lower is better.
     *
     * * `increase` - Increase
     * * `decrease` - Decrease */
    direction?: BetDirectionEnumApi
    /**
     * Display unit, for example %.
     * @maxLength 32
     */
    unit?: string
    /**
     * Budget for this bet in USD cents.
     * @minimum 0
     * @maximum 1000000000
     */
    budget_cents?: number
}

/**
 * * `` -
 * * `task` - Task
 * * `experiment` - Experiment
 * * `flag` - Flag
 * * `insight` - Insight
 * * `pull_request` - Pull request
 */
export type BetActivityResourceEnumApi = (typeof BetActivityResourceEnumApi)[keyof typeof BetActivityResourceEnumApi]

export const BetActivityResourceEnumApi = {
    Task: 'task',
    Experiment: 'experiment',
    Flag: 'flag',
    Insight: 'insight',
    PullRequest: 'pull_request',
} as const

export const BetsActivityApiResource = { ...BetActivityResourceEnumApi, ...BlankEnumApi } as const
export interface BetsActivityApi {
    /** Stable activity entry identifier. */
    id: string
    /** Recorded time of this event. */
    at: string
    /** Summary of the recorded event. */
    title: string
    /** Related work or changed fields. */
    detail: string
    /** Native resource to open.
     *
     * * `` -
     * * `task` - Task
     * * `experiment` - Experiment
     * * `flag` - Flag
     * * `insight` - Insight
     * * `pull_request` - Pull request */
    resource: (typeof BetsActivityApiResource)[keyof typeof BetsActivityApiResource]
    /** Identifier or URL of the linked native resource. */
    resource_id: string
}

export interface BetsIdeaApi {
    /**
     * The owner's idea, in one sentence.
     * @maxLength 255
     */
    title: string
}

/**
 * * `running` - Start or resume
 * * `paused` - Pause
 * * `closed` - Close
 */
export type BetStatusChangeEnumApi = (typeof BetStatusChangeEnumApi)[keyof typeof BetStatusChangeEnumApi]

export const BetStatusChangeEnumApi = {
    Running: 'running',
    Paused: 'paused',
    Closed: 'closed',
} as const

export interface BetsStatusApi {
    /** Resume, pause or close the bet.
     *
     * * `running` - Start or resume
     * * `paused` - Pause
     * * `closed` - Close */
    status: BetStatusChangeEnumApi
}

export interface BetsPlanInputApi {
    /**
     * Days the experiment runs.
     * @minimum 2
     * @maximum 365
     */
    days: number
    /**
     * Smallest change worth finding, in percent.
     * @minimum 0.1
     * @maximum 100
     */
    mde: number
    /**
     * People a day who see the change.
     * @minimum 1
     */
    audience: number
}

export interface BetsWorkActionApi {
    /** Work item belonging to this bet. */
    work_id: string
    /** Build a proposed idea, dismiss it, retry stuck work, drop an idea in progress, or extend its experiment.
     *
     * * `retry` - Retry
     * * `drop` - Drop
     * * `build` - Build
     * * `dismiss` - Dismiss
     * * `extend` - Extend */
    action: BetWorkActionEnumApi
    /**
     * Why the idea is dismissed.
     * @maxLength 1000
     */
    reason?: string
    /** The experiment plan the owner approves with a build. */
    plan?: BetsPlanInputApi
}

export interface BetsStepModelWriteApi {
    /**
     * Model ID, or empty for the project default.
     * @maxLength 200
     */
    model: string
    /**
     * Reasoning effort.
     * @maxLength 20
     */
    reasoning_effort?: string
    /** Who pays for this step's model use.
     *
     * * `credits` - PostHog credits
     * * `subscription` - ChatGPT plan */
    billing: StepBillingEnumApi
}

export interface BetsStepModelsWriteApi {
    /** Model for the Scout. */
    scout?: BetsStepModelWriteApi
    /** Model for tracking checks. */
    tracking?: BetsStepModelWriteApi
    /** Model for building ideas. */
    idea?: BetsStepModelWriteApi
}

export interface PatchedBetsSettingsWriteApi {
    /**
     * Project budget in USD cents.
     * @minimum 0
     * @maximum 1000000000
     */
    budget_cents?: number
    /**
     * Saved insight for the project North Star.
     * @maxLength 32
     */
    north_star_insight?: string
    /**
     * Shortest experiment run in hours. Zero lets the plan decide.
     * @minimum 0
     * @maximum 1440
     */
    min_run_hours?: number
    /**
     * Smallest relative change, in percent, an experiment plans to find.
     * @minimum 0.1
     * @maximum 100
     */
    mde_percent?: number
    /**
     * Hours the goal metric must stay at the target before the bet counts as reached.
     * @minimum 0
     * @maximum 1440
     */
    goal_confirm_hours?: number
    /** Model and billing per step. */
    step_models?: BetsStepModelsWriteApi
}

export type BetsMetricPreviewRetrieveParams = {
    /**
     * Short ID of the saved insight to preview.
     * @minLength 1
     * @maxLength 32
     */
    insight: string
}
