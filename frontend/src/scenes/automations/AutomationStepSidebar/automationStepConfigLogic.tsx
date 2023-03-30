import { actions, key, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { AnyAutomationStep, AutomationStepCategory, AutomationStepConfigType, AutomationStepKind } from '../schema'

import {
    GithubIcon,
    IconAction,
    IconApps,
    IconArticle,
    IconCoffee,
    IconCohort,
    IconEvent,
    IconFlag,
    IconMonitor,
    IconPerson,
    IconSlack,
    IconWebhook,
} from 'lib/lemon-ui/icons'
import { EventSentConfig, WebhookDestinationConfig } from './AutomationStepConfig'
import { automationLogic, AutomationLogicProps } from '../automationLogic'

import type { automationStepConfigLogicType } from './automationStepConfigLogicType'
import { applyEventToPayloadTemplate } from './webhookDestinationUtils'
import { EventType, JsonType } from '~/types'
import { automationStepMenuLogic } from './automationStepMenuLogic'

export const kindToConfig: Record<AutomationStepKind, AutomationStepConfigType> = {
    [AutomationStepKind.EventSource]: {
        icon: <IconEvent />,
        label: 'Event sent',
        configComponent: <EventSentConfig />,
    },
    [AutomationStepKind.ActionSource]: { icon: <IconAction />, label: 'Action triggered' },
    [AutomationStepKind.PauseForLogic]: { icon: <IconCoffee />, label: 'Pause for' },
    [AutomationStepKind.PauseUntilLogic]: { icon: <IconCoffee />, label: 'Pause until' },
    [AutomationStepKind.GithubIssueDestination]: { icon: <GithubIcon />, label: 'Create a Github ticket' },
    [AutomationStepKind.UserPropertyDestination]: { icon: <IconPerson />, label: 'Set user property' },
    [AutomationStepKind.CohortDestination]: { icon: <IconCohort />, label: 'Add to cohort' },
    [AutomationStepKind.FeatureFlagDestination]: { icon: <IconFlag />, label: 'Add to feature flags' },
    [AutomationStepKind.WebhookDestination]: {
        icon: <IconWebhook />,
        label: 'Send a webhook',
        configComponent: <WebhookDestinationConfig />,
    },
    [AutomationStepKind.SlackDestination]: { icon: <IconSlack />, label: 'Send to slack' },
    [AutomationStepKind.ZapierDestination]: { icon: <IconApps />, label: 'Send to Zapier' },
    [AutomationStepKind.EmailDestination]: { icon: <IconArticle />, label: 'Send an email' },
    [AutomationStepKind.InAppMessageDestination]: { icon: <IconMonitor />, label: 'In-app message' },
}

export const automationStepConfigLogic = kea<automationStepConfigLogicType>([
    props({} as AutomationLogicProps),
    // key((props) => props.automationId || 'new'),
    path(['scenes', 'automations', 'AutomationStepSidebar', 'automationStepConfigLogic']),
    connect((props: AutomationLogicProps) => ({
        values: [automationLogic(props), ['flowSteps', 'steps']],
        actions: [
            automationLogic(props),
            ['setAutomationValue', 'setAutomationValues'],
            automationStepMenuLogic,
            ['openMenu', 'closeMenu'],
        ],
    })),
    actions({
        setActiveStepId: (id: string | null) => ({ id }),
        updateActiveStep: (id: string, partialStep: Node) => ({ id, partialStep }),
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
            // TODO: rename to webhook example event
            JSON.stringify(
                {
                    id: 'id_1234',
                    distinct_id: 'distinct_id_5678',
                    properties: { $feedback: 'hello' },
                    event: 'Feedback Sent',
                    timestamp: '2023-04-01 16:44:34',
                    person: {
                        properties: { name: 'Max Hedgehog', email: 'maxthehedgehog@hedgehouse.com' },
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
            (activeStepId, flowSteps): Node | null => {
                return flowSteps.find((step: Node) => step.id === activeStepId) || null
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
            (activeStep: Node | null, exampleEvent: Partial<EventType>): JsonType | string | null => {
                if (!activeStep) {
                    return null
                }
                try {
                    const examplePayload = applyEventToPayloadTemplate(
                        JSON.parse(activeStep?.data?.payload),
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
            const newSteps = values.steps.map((s) => {
                if (s.id === id) {
                    const newData = { ...s.data, ...partialStep.data }
                    return { ...s, ...partialStep, data: newData }
                } else {
                    return s
                }
            })
            console.debug('listeners.updateActiveStep', id, partialStep, newSteps)
            actions.setAutomationValue('steps', newSteps)
        },
        setActiveStepId: ({ id }) => {
            if (id !== null) {
                actions.closeMenu()
                if (
                    values.activeStep.data.kind === AutomationStepKind.WebhookDestination &&
                    values.activeStep.data.payload === undefined
                ) {
                    actions.updateActiveStep(id, {
                        payload: JSON.stringify(
                            {
                                full_event: '{event}',
                                person: '{person}',
                                message: 'Hi {event.person.properties.email}!',
                            },
                            null,
                            4
                        ),
                    })
                }
            }
        },
        openMenu: () => {
            console.debug('listeners.openMenu')
            actions.setActiveStepId(null)
        },
    })),
])
