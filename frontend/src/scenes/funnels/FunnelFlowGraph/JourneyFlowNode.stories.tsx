import { Meta, StoryFn } from '@storybook/react'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { FunnelStepWithConversionMetrics } from '~/types'

import { InsightProvider, makeStep } from './__mocks__/nodeStoryUtils'
import { NODE_WIDTH } from './funnelFlowGraphLogic'
import { OptionalChip } from './FunnelFlowNode'
import { StepNodeShell } from './StepNodeShell'

function JourneyNodeStory({
    step,
    stepIndex,
    isOptional = false,
}: {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    isOptional?: boolean
}): JSX.Element {
    return (
        <InsightProvider>
            <StepNodeShell
                step={step}
                stepIndex={stepIndex}
                containerClassName={
                    isOptional ? 'border-dashed border-primary bg-fill-highlight-50' : 'border-primary bg-bg-light'
                }
                handles={<></>}
                eventDisplay={<EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />}
                headerExtra={isOptional ? <OptionalChip /> : undefined}
                headerAction={<More overlay={<></>} />}
            />
        </InsightProvider>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Customer Analytics/Journeys/Nodes/JourneyFlowNode',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2024-01-15',
    },
}
export default meta

export const FirstStep: StoryFn = () => <JourneyNodeStory step={makeStep('Sign up', 0, 100, 100)} stepIndex={0} />

export const GreenProgressBar: StoryFn = () => (
    <JourneyNodeStory step={makeStep('Complete profile', 1, 80, 100)} stepIndex={1} />
)

export const YellowProgressBar: StoryFn = () => (
    <JourneyNodeStory step={makeStep('First action', 2, 50, 100)} stepIndex={2} />
)

export const RedProgressBar: StoryFn = () => (
    <JourneyNodeStory step={makeStep('Activation', 3, 10, 100)} stepIndex={3} />
)

export const EmptyProgressBar: StoryFn = () => (
    <JourneyNodeStory step={makeStep('Activation', 3, 0, 100)} stepIndex={3} />
)

export const OptionalStep: StoryFn = () => (
    <JourneyNodeStory step={makeStep('Complete profile', 1, 50, 100)} stepIndex={1} isOptional />
)

export const AllVariants: StoryFn = () => {
    const spacing = NODE_WIDTH + 20
    return (
        <div className="flex flex-wrap gap-4" style={{ maxWidth: spacing * 3 }}>
            <JourneyNodeStory step={makeStep('Sign up', 0, 100, 100)} stepIndex={0} />
            <JourneyNodeStory step={makeStep('Complete profile', 1, 80, 100)} stepIndex={1} />
            <JourneyNodeStory step={makeStep('First action', 2, 50, 100)} stepIndex={2} />
            <JourneyNodeStory step={makeStep('Activation', 3, 10, 100)} stepIndex={3} />
            <JourneyNodeStory step={makeStep('Churn', 4, 0, 100)} stepIndex={4} />
            <JourneyNodeStory step={makeStep('Optional step', 1, 50, 100)} stepIndex={1} isOptional />
        </div>
    )
}
