import { actions, kea, path, reducers, selectors } from 'kea'
import { AnyAutomationStep, AutomationStepCategory, AutomationStepConfigType, AutomationStepKind } from '../schema'

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
import { EventSentConfig } from './AutomationStepConfig'
import { uuid } from 'lib/utils'

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
    [AutomationStepKind.WebhookDestination]: { icon: <IconWebhook />, label: 'Send a webhook' },
    // 'Send to slack': { icon: <IconSlack />, label: 'Send to slack' },
    // 'Send to Zapier': { icon: <IconApps />, label: 'Send to Zapier' },
    // 'Send an email': { icon: <IconArticle />, label: 'Send an email' },
    // 'In-app message': { icon: <IconMonitor />, label: 'In-app message' },
}

export const automationStepConfigLogic = kea([
    path(['scenes', 'automations', 'AutomationStepSidebar', 'automationStepConfigLogic']),
    actions({
        setActiveStepId: (id: string) => ({ id }),
        updateActiveStep: (id: string, activeStepUpdates: Partial<AnyAutomationStep>) => ({ id, activeStepUpdates }),
    }),
    reducers({
        activeSteps: [
            [
                {
                    kind: AutomationStepKind.EventSource,
                    id: uuid(),
                    category: AutomationStepCategory.Source,
                    filters: [],
                },
            ] as AnyAutomationStep[],
            {
                updateActiveStep: (activeSteps, { id, activeStepUpdates }) => {
                    return activeSteps.map((activeStep: AnyAutomationStep) => {
                        if (activeStep.id === id) {
                            return {
                                ...activeStep,
                                ...activeStepUpdates,
                            }
                        } else {
                            return activeStep
                        }
                    })
                },
            },
        ],
        activeStepId: [
            null as null | string,
            {
                setActiveStepId: (_, { id }) => id,
                closeStepConfig: () => null,
            },
        ],
        stepOptions: [stepOptions as AnyAutomationStep[], {}],
        stepCategories: [Object.values(AutomationStepCategory), {}],
    }),
    selectors({
        activeStep: [
            (selectors) => [selectors.activeStepId, selectors.activeSteps],
            (activeStepId: string, activeSteps: AnyAutomationStep[]): AnyAutomationStep | null => {
                return activeSteps.find((step: AnyAutomationStep) => step.id === activeStepId) || null
            },
        ],
        activeStepConfig: [
            (selectors) => [selectors.activeStep],
            (activeStep: AnyAutomationStep | null): AutomationStepConfigType | null => {
                if (!activeStep) {
                    return null
                }
                return kindToConfig[activeStep.id]
            },
        ],
    }),
])
