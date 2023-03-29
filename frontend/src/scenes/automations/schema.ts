import { UserBasicType } from '~/types'

export enum AutomationStepCategory {
    Source = 'Source',
    Logic = 'Logic',
    Destination = 'Destination',
}

export enum AutomationStepKind {
    // Sources
    EventSource = 'EventSource',
    ActionSource = 'ActionSource',

    // Business Logic
    // e.g. Delay, Branch
    PauseForLogic = 'PauseForLogic',
    PauseUntilLogic = 'PauseUntilLogic',

    // Destinations
    GithubIssueDestination = 'GithubIssueDestination',
    UserPropertyDestination = 'UserPropertyDestination',
    CohortDestination = 'CohortDestination',
    FeatureFlagDestination = 'FeatureFlagDestination',
    SlackDestination = 'SlackDestination',
    ZapierDestination = 'ZapierDestination',
    EmailDestination = 'EmailDestination',
    InAppMessageDestination = 'InAppMessageDestination',
    WebhookDestination = 'WebhookDestination',
}

export type AutomationStep = {
    id: string
}

export type AutomationGenericStep = AutomationStep & {
    kind: AutomationStepKind
    category: AutomationStepCategory
}

export type AutomationEventSourceStep = AutomationStep & {
    kind: AutomationStepKind.EventSource
    category: AutomationStepCategory.Source
    // event
    // filters
}

export type AutomationWebhookDestinationStep = AutomationStep & {
    kind: AutomationStepKind.WebhookDestination
    category: AutomationStepCategory.Destination
    url: string
}

export type AnyAutomationStep = AutomationEventSourceStep | AutomationWebhookDestinationStep | AutomationGenericStep

export type AutomationEdge = {
    source: string
    target: string
}

export type Automation = {
    id: number | 'new'
    name: string
    description?: string
    created_at: string | null
    created_by: UserBasicType | null
    updated_at: string | null
    steps: AnyAutomationStep[]
    edges: AutomationEdge[]
}

export type AutomationStepConfigType = {
    label: string
    description?: string
    icon: JSX.Element
}
