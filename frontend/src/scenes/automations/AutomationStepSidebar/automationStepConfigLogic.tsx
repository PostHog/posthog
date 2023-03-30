import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import {
    AnyAutomationStep,
    AutomationStepCategory,
    AutomationStepConfigType,
    AutomationStepKind,
    AutomationWebhookDestinationStep,
} from '../schema'

import {
    // GithubIcon,
    // IconAction,
    // IconApps,
    // IconArticle,
    // IconCoffee,
    // IconCohort,
    IconEvent,
    // IconFlag,
    // IconMonitor,
    // IconPerson,
    // IconSlack,
    IconWebhook,
} from 'lib/lemon-ui/icons'
import { automationLogic, AutomationLogicProps } from '../automationLogic'

import { EventSentConfig, WebhookDestinationConfig } from './AutomationStepConfig'
import { uuid } from 'lib/utils'

import type { automationStepConfigLogicType } from './automationStepConfigLogicType'

const id = uuid()
const exampleWebhook = {
    kind: AutomationStepKind.WebhookDestination,
    id: id,
    category: AutomationStepCategory.Destination,
    url: 'https://posthog.com',
    payload: JSON.stringify(
        {
            event: '{event.event}',
            properties: '{event.properties}',
            person_ids: '{event.person.distinct_ids}',
        },
        null,
        4
    ),
} as AutomationWebhookDestinationStep

// given a JSON payload which can contain any properties
// replace the parts in curly brackets with the event property values if they exist
// for example:
// payload template = { "message": "{event.name}", "nested_message": "{event.person.property.name.first_name}" }
// event = { "name": "Hello", person: { property: { name: { first_name: "Luke" }}} }
// should give the output { "message": "Hello", "nested_message": "Luke" }
type JsonType = { [key: string]: any }
type EventType = { [key: string]: any }

function applyEventToPayloadTemplate(payloadTemplate: JsonType, event: Partial<EventType>): JsonType {
    function replaceTemplateRecursive(obj: any, path: string[]): any {
        if (typeof obj === 'string') {
            const matches = obj.match(/\{event\.[a-zA-Z0-9_.]+\}/g)
            if (matches) {
                for (const match of matches) {
                    const propertyPath = match.slice(7, -1).split('.')
                    let value = event
                    for (const key of propertyPath) {
                        if (value === undefined) {
                            break
                        }
                        value = value[key]
                    }
                    if (value !== undefined) {
                        if (obj === match) {
                            return value
                        } else {
                            obj = obj.replace(match, value)
                        }
                    }
                }
            }
            return obj
        } else if (Array.isArray(obj)) {
            return obj.map((item, index) => replaceTemplateRecursive(item, path.concat(index.toString())))
        } else if (typeof obj === 'object' && obj !== null) {
            const newObj: { [key: string]: any } = {}
            for (const key of Object.keys(obj)) {
                newObj[key] = replaceTemplateRecursive(obj[key], path.concat(key))
            }
            return newObj
        } else {
            return obj
        }
    }

    return replaceTemplateRecursive(payloadTemplate, [])
}

const stepOptions: AnyAutomationStep[] = [
    {
        kind: AutomationStepKind.EventSource,
        id: 'new',
        category: AutomationStepCategory.Source,
        filters: [],
    },
    // { kind: AutomationStepKind.ActionSource, category: AutomationStepCategory.Source },
    // { kind: AutomationStepKind.PauseForLogic, category: AutomationStepCategory.Logic },
    // { kind: AutomationStepKind.PauseUntilLogic, category: AutomationStepCategory.Logic },
    // {
    //     kind: AutomationStepKind.GithubIssueDestination,
    //     category: AutomationStepCategory.Destination,
    // },
    // {
    //     kind: AutomationStepKind.UserPropertyDestination,
    //     category: AutomationStepCategory.Destination,
    // },
    // { kind: AutomationStepKind.CohortDestination, category: AutomationStepCategory.Destination },
    // {
    //     kind: AutomationStepKind.FeatureFlagDestination,
    //     category: AutomationStepCategory.Destination,
    // },
    { kind: AutomationStepKind.WebhookDestination, id: 'new', category: AutomationStepCategory.Destination },
    // { kind: AutomationStepKind.SlackDestination, category: AutomationStepCategory.Destination },
    // { kind: AutomationStepKind.ZapierDestination, category: AutomationStepCategory.Destination },
    // { kind: AutomationStepKind.EmailDestination, category: AutomationStepCategory.Destination },
    // {
    //     kind: AutomationStepKind.InAppMessageDestination,
    //     category: AutomationStepCategory.Destination,
    // },
]

export const kindToConfig: Record<AutomationStepKind, AutomationStepConfigType> = {
    [AutomationStepKind.EventSource]: {
        icon: <IconEvent />,
        label: 'Event sent',
        configComponent: <EventSentConfig />,
    },
    // [AutomationStepKind.ActionSource]: { icon: <IconAction />, label: 'Action triggered' },
    // 'Pause for': { icon: <IconCoffee />, label: 'Pause for' },
    // 'Pause until': { icon: <IconCoffee />, label: 'Pause until' },
    // 'Create a Github ticket': { icon: <GithubIcon />, label: 'Create a Github ticket' },
    // 'Set user property': { icon: <IconPerson />, label: 'Set user property' },
    // 'Add to cohort': { icon: <IconCohort />, label: 'Add to cohort' },
    // 'Add to feature flags': { icon: <IconFlag />, label: 'Add to feature flags' },
    [AutomationStepKind.WebhookDestination]: {
        icon: <IconWebhook />,
        label: 'Send a webhook',
        configComponent: <WebhookDestinationConfig />,
    },
    // 'Send to slack': { icon: <IconSlack />, label: 'Send to slack' },
    // 'Send to Zapier': { icon: <IconApps />, label: 'Send to Zapier' },
    // 'Send an email': { icon: <IconArticle />, label: 'Send an email' },
    // 'In-app message': { icon: <IconMonitor />, label: 'In-app message' },
}

export const automationStepConfigLogic = kea<automationStepConfigLogicType>([
    props({} as AutomationLogicProps),
    // key((props) => props.automationId || 'new'),
    path(['scenes', 'automations', 'AutomationStepSidebar', 'automationStepConfigLogic']),
    connect((props: AutomationLogicProps) => ({
        values: [automationLogic(props), ['flowSteps', 'steps']],
        actions: [automationLogic(props), ['setAutomationValue', 'setAutomationValues']],
    })),
    actions({
        setActiveStepId: (id: string | null) => ({ id }),
        updateActiveStep: (id: string, partialStep: Partial<AnyAutomationStep>) => ({ id, partialStep }),
        setExampleEvent: (exampleEvent: string) => exampleEvent,
    }),
    reducers({
        activeStepId: [
            null as null | string,
            {
                setActiveStepId: (_, { id }) => id,
            },
        ],
        stepCategories: [Object.values(AutomationStepCategory), {}],
        exampleEvent: [
            JSON.stringify(
                {
                    id: 'id_1234',
                    distinct_id: 'distinct_id_5678',
                    properties: { $feedback: 'hello' },
                    event: 'Feedback Sent',
                    timestamp: '2023-04-01 16:44:34',
                    person: {
                        properties: { name: 'Max Hedgehog' },
                        is_identified: true,
                        distinct_ids: ['distinct_id_5678'],
                    },
                },
                null,
                4
            ) as string,
            {
                setExampleEvent: (_, { exampleEvent }) => ({ exampleEvent }),
            },
        ],
    }),
    selectors({
        activeStep: [
            (s) => [s.activeStepId, s.flowSteps],
            (activeStepId, flowSteps): AnyAutomationStep | null => {
                return flowSteps.find((step: AnyAutomationStep) => step.id === activeStepId) || null
            },
        ],
        activeStepConfig: [
            (s) => [s.activeStep],
            (activeStep): AutomationStepConfigType | null => {
                if (!activeStep) {
                    return null
                }
                return kindToConfig[activeStep.data.kind]
            },
        ],
        previewPayload: [
            (selectors) => [selectors.activeStep, selectors.exampleEvent],
            (activeStep: AnyAutomationStep | null, exampleEvent: Partial<EventType>): JsonType | string | null => {
                if (!activeStep) {
                    return null
                }
                try {
                    const examplePayload = applyEventToPayloadTemplate(
                        JSON.parse(activeStep.payload),
                        JSON.parse(exampleEvent)
                    )
                    return examplePayload
                } catch (e) {
                    return 'Invalid JSON' + e
                }
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        updateActiveStep: ({ id, partialStep }) => {
            const newSteps = values.steps.map((s) => (s.id === id ? { ...s, ...partialStep } : s))
            console.debug('listeners.updateActiveStep', id, partialStep, newSteps)
            actions.setAutomationValue('steps', newSteps)
        },
    })),
])
