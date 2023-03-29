import { UserBasicType } from '~/types'

export enum AutomationStepKind {
    // Sources
    EventSource = 'EventSource',

    // Business Logic
    // e.g. Delay, Branch

    // Destinations
    WebhookDestination = 'WebhookDestination',
}

export type AutomationStep = {
    id: string
}

export type AutomationEventSourceStep = AutomationStep & {
    kind: AutomationStepKind.EventSource
    // event
    // filters
}

export type AutomationWebhookDestinationStep = AutomationStep & {
    kind: AutomationStepKind.WebhookDestination
    url: string
}

export type AnyAutomationStep = AutomationEventSourceStep | AutomationWebhookDestinationStep

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
