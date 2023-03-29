export enum AutomationStepKind {
    // Sources
    EventSource = 'EventSource',

    // Business Logic
    // e.g. Delay, Branch

    // Destinations
    WebhookDestination = 'WebhookDestination',
}

export type AutomationEventSourceStep = {
    kind: AutomationStepKind.EventSource
    // event
    // filters
}

export type AutomationWebhookDestinationStep = {
    kind: AutomationStepKind.WebhookDestination
    url: string
}

export type AnyAutomationStep = AutomationEventSourceStep | AutomationWebhookDestinationStep

export type AutomationEdge = {
    source: AnyAutomationStep
    target: AnyAutomationStep
}

export type Automation = {
    name: string
    steps: AnyAutomationStep[]
    edges: AutomationEdge[]
}
