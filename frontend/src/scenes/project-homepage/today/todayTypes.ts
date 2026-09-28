export type TodayEvidenceKind =
    | 'analytics'
    | 'code'
    | 'error'
    | 'experiment'
    | 'flag'
    | 'replay'
    | 'survey'
    | 'trace'
    | 'warehouse'

export type TodayStoryIcon =
    | 'pr'
    | 'experiment'
    | 'replay'
    | 'error'
    | 'llm'
    | 'survey'
    | 'analytics'
    | 'trace'
    | 'inbox'
    | 'home'

export type TodayActionTone = 'success' | 'warning' | 'info'

export type TodayScenarioId = 'growth' | 'checkout' | 'llm-cost'

export interface TodayEvidence {
    product: string
    value: string
    detail: string
    color: string
    kind: TodayEvidenceKind
}

export interface TodayActionRun {
    loading: string
    steps: string[]
    result: string
    live: string
}

export interface TodayFollowUp {
    title: string
    summary: string
}

export interface TodayAction {
    primary: string
    status: string
    tone: TodayActionTone
    confirmation: string
    done?: string
    pr?: string
    icon?: 'ship'
    waitingOn?: string
    advisory?: { from: string; text: string }
    run?: TodayActionRun
    followUp?: TodayFollowUp
    /** Where the action takes the user, for stories built from real reports. */
    href?: string
}

export interface TodayStory {
    id: string
    title: string
    meta: string
    color: string
    icon: TodayStoryIcon
    heading: string
    paragraphs: string[]
    evidence: TodayEvidence[]
    action: TodayAction
    /** Starts out done, like a story the user already acted on. */
    completed?: boolean
    /** Only shown after the user asks to load more. */
    secondary?: boolean
}

/** One run of text in the briefing. `link` points at a story id and `highlight` marks the one that needs a decision. */
export interface TodayBriefingSegment {
    text: string
    link?: string
    highlight?: boolean
}

export interface TodayFollowUpOption {
    id: string
    label: string
    phrase: string
    chip: string
}

export interface TodayAgentOption {
    id: 'mine' | 'posthog'
    name: string
    detail: string
    sent: string
}

export interface TodayMenuOption {
    id: string
    label: string
    detail?: string
}

export interface TodayScenarioStep {
    label: string
    value: string
    width: number
}

export interface TodayScenarioEvidence {
    id: string
    eyebrow: string
    title: string
    summary: string
    source: string
    color: string
    readyAfter: number
    steps: TodayScenarioStep[]
    recommendation: string
    action: string
    done: string
    lever?: string
    impact?: number
}

export interface TodayScenario {
    id: TodayScenarioId
    suggestion: string
    signal: string
    prompt: string
    conclusion: string
    thinking: string[]
    target?: { label: string; goal: number }
    evidence: TodayScenarioEvidence[]
}

export interface TodayConversation {
    id: string
    question: string
    scenarioId: TodayScenarioId
    status: 'thinking' | 'answered'
}

export interface TodayItem {
    evidenceId: string
    title: string
    action: string
    color: string
    scenarioId: TodayScenarioId
    conversationId: string
}

export interface TodayRecentError {
    name: string
    detail: string
    count: string
    time: string
}

export interface TodayRecording {
    title: string
    detail: string
    duration: string
    step: string
    note: string
}
