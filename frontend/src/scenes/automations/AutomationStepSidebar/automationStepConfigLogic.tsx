import { actions, key, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
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
import { automationLogic, AutomationLogicProps } from '../automationLogic'

import type { automationStepConfigLogicType } from './automationStepConfigLogicType'

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

export const automationStepConfigLogic = kea<automationStepConfigLogicType>([
    props({} as AutomationLogicProps),
    // key((props) => props.automationId || 'new'),
    path(['scenes', 'automations', 'AutomationStepSidebar', 'automationStepConfigLogic']),
    connect((props: AutomationLogicProps) => ({
        values: [automationLogic(props), ['flowSteps']],
    })),
    actions({
        setActiveStepId: (id: string) => ({ id }),
        updateActiveStep: (id: string, activeStepUpdates: Partial<AnyAutomationStep>) => ({ id, activeStepUpdates }),
    }),
    reducers({
        activeStepId: [
            null as null | string,
            {
                setActiveStepId: (_, { id }) => id,
            },
        ],
        stepCategories: [Object.values(AutomationStepCategory), {}],
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
    }),
])
