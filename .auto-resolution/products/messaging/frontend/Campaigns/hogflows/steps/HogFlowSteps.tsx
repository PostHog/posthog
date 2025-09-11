import { Node } from '@xyflow/react'
import { useValues } from 'kea'
import { useMemo } from 'react'

import {
    IconBolt,
    IconClock,
    IconDay,
    IconDecisionTree,
    IconHourglass,
    IconLeave,
    IconLetter,
    IconPercentage,
    IconWebhooks,
} from '@posthog/icons'

import { IconTwilio } from 'lib/lemon-ui/icons'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { HogFunctionTemplateType } from '~/types'

import { campaignLogic } from '../../campaignLogic'
import { HogFlowAction } from '../types'
import { StepConditionalBranchConfiguration } from './StepConditionalBranch'
import { StepDelayConfiguration } from './StepDelay'
import { StepExitConfiguration } from './StepExit'
import { StepFunctionConfiguration } from './StepFunction'
import { StepRandomCohortBranchConfiguration } from './StepRandomCohortBranch'
import { StepTriggerConfiguration } from './StepTrigger'
import { StepWaitUntilConditionConfiguration } from './StepWaitUntilCondition'
import { StepWaitUntilTimeWindowConfiguration } from './StepWaitUntilTimeWindow'

type HogFlowStepBuilder<T extends HogFlowAction['type']> = {
    type: T
    icon: (
        action: Extract<HogFlowAction, { type: T }>,
        hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
    ) => JSX.Element
    color: (action: Extract<HogFlowAction, { type: T }>, isDarkModeOn: boolean) => string
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
}

type HogFlowStep<T extends HogFlowAction['type']> = {
    type: T
    icon: JSX.Element
    color: string
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
}

const HogFlowStepConfigs: Partial<{
    [K in HogFlowAction['type']]: HogFlowStepBuilder<K>
}> = {
    conditional_branch: {
        type: 'conditional_branch',
        icon: () => <IconDecisionTree />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#35C46F' : '#005841'),
        renderConfiguration: (node) => <StepConditionalBranchConfiguration node={node} />,
    },
    delay: {
        type: 'delay',
        icon: () => <IconClock />,
        color: () => '#a20031',
        renderConfiguration: (node) => <StepDelayConfiguration node={node} />,
    },
    exit: {
        type: 'exit',
        icon: () => <IconLeave />,
        color: () => '#4b4b4b',
        renderConfiguration: (node) => <StepExitConfiguration node={node} />,
    },

    random_cohort_branch: {
        type: 'random_cohort_branch',
        icon: () => <IconPercentage />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#D6247B' : '#9a004d'),
        renderConfiguration: (node) => <StepRandomCohortBranchConfiguration node={node} />,
    },
    trigger: {
        type: 'trigger',
        icon: () => <IconBolt />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#35C46F' : '#005841'),
        renderConfiguration: (node) => <StepTriggerConfiguration node={node} />,
    },
    wait_until_condition: {
        type: 'wait_until_condition',
        icon: () => <IconHourglass />,
        color: () => '#ffaa00',
        renderConfiguration: (node) => <StepWaitUntilConditionConfiguration node={node} />,
    },
    wait_until_time_window: {
        type: 'wait_until_time_window',
        icon: () => <IconDay />,
        color: () => '#FF653F',
        renderConfiguration: (node) => <StepWaitUntilTimeWindowConfiguration node={node} />,
    },

    // We can remove these later
    function_email: {
        type: 'function_email',
        icon: () => <IconLetter />,
        color: (_, isDarkModeOn) => (isDarkModeOn ? '#2F80FA' : '#2F80FA'),
        renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    },
    function_sms: {
        type: 'function_sms',
        icon: () => <IconTwilio />,
        color: () => '#f22f46',
        renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    },
    function: {
        type: 'function',
        icon: (action, hogFunctionTemplatesById) => {
            if (action.config.template_id === 'template-email') {
                return <IconLetter />
            }

            if (action.config.template_id === 'template-webhook') {
                return <IconWebhooks />
            }

            const template = hogFunctionTemplatesById[action.config.template_id]
            return template?.icon_url ? (
                <img className="LemonIcon rounded" src={template.icon_url} alt={template.name} />
            ) : (
                <IconBolt />
            )
        },
        color: (action, isDarkModeOn) => {
            if (action.config.template_id === 'template-email') {
                return isDarkModeOn ? '#2F80FA' : '#2F80FA'
            }

            if (action.config.template_id === 'template-webhook') {
                return isDarkModeOn ? '#B52AD9' : '#6500ae'
            }

            return isDarkModeOn ? '#F8BE2A' : '#F44D01'
        },
        renderConfiguration: (node) => <StepFunctionConfiguration node={node} />,
    },
} as const

// Type-safe accessor that preserves the key type
export function getHogFlowStep<T extends HogFlowAction['type']>(
    action: Extract<HogFlowAction, { type: T }>,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>,
    isDarkModeOn = false
): HogFlowStep<T> | undefined {
    const type = action.type
    const builder = HogFlowStepConfigs[type] as HogFlowStepBuilder<T> | undefined
    if (!builder) {
        return undefined
    }
    return {
        type,
        icon: builder.icon(action, hogFunctionTemplatesById),
        color: builder.color(action, isDarkModeOn),
        renderConfiguration: builder.renderConfiguration,
    }
}

export function useHogFlowStep<T extends HogFlowAction['type']>(
    action?: Extract<HogFlowAction, { type: T }>
): HogFlowStep<T> | undefined {
    const { hogFunctionTemplatesById } = useValues(campaignLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return useMemo(() => {
        if (!action) {
            return undefined
        }
        return getHogFlowStep(action, hogFunctionTemplatesById, isDarkModeOn)
    }, [action, hogFunctionTemplatesById, isDarkModeOn])
}
