import { Meta, StoryFn } from '@storybook/react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { FunnelStepWithConversionMetrics } from '~/types'

import { InsightProvider, makeStep } from './__mocks__/nodeStoryUtils'
import { NODE_WIDTH } from './funnelFlowGraphLogic'
import { StepNodeShell } from './StepNodeShell'

function BuilderNodeStory({
    step,
    stepIndex,
    hasEvent = true,
    canRemove = true,
}: {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    hasEvent?: boolean
    canRemove?: boolean
}): JSX.Element {
    const hasConversionData = step.count != null && step.count > 0

    return (
        <InsightProvider>
            <StepNodeShell
                step={step}
                stepIndex={stepIndex}
                containerClassName="group/builder-node border-primary bg-bg-light"
                hasConversionData={hasConversionData}
                handles={<></>}
                eventDisplay={
                    hasEvent ? (
                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />
                    ) : (
                        <LemonButton type="secondary" size="small">
                            Select an event
                        </LemonButton>
                    )
                }
                headerAction={
                    canRemove ? <LemonButton icon={<IconX />} size="xsmall" tooltip="Remove step" noPadding /> : <></>
                }
                emptyState={
                    <span className="text-xs text-muted italic">
                        {hasEvent ? 'Waiting for data...' : 'Pick an event to see data'}
                    </span>
                }
            />
        </InsightProvider>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Customer Analytics/Journeys/Nodes/BuilderStepNode',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2024-01-15',
    },
}
export default meta

export const WithEventAndData: StoryFn = () => (
    <BuilderNodeStory step={makeStep('Sign up', 0, 100, 100)} stepIndex={0} />
)

export const WithEventNoData: StoryFn = () => (
    <BuilderNodeStory step={makeStep('First action', 2, 0, 100)} stepIndex={2} />
)

export const NoEvent: StoryFn = () => {
    const emptyStep = {
        ...makeStep('Select an event', 0, 0, 0),
        action_id: null,
        count: null,
    } as unknown as FunnelStepWithConversionMetrics
    return <BuilderNodeStory step={emptyStep} stepIndex={0} hasEvent={false} />
}

export const SingleStep: StoryFn = () => (
    <BuilderNodeStory step={makeStep('Sign up', 0, 100, 100)} stepIndex={0} canRemove={false} />
)

export const AllVariants: StoryFn = () => {
    const spacing = NODE_WIDTH + 20
    const emptyStep = {
        ...makeStep('Select an event', 0, 0, 0),
        action_id: null,
        count: null,
    } as unknown as FunnelStepWithConversionMetrics

    return (
        <InsightProvider>
            <div className="flex flex-wrap gap-4" style={{ maxWidth: spacing * 3 }}>
                <StepNodeShell
                    step={makeStep('Sign up', 0, 100, 100)}
                    stepIndex={0}
                    containerClassName="group/builder-node border-primary bg-bg-light"
                    hasConversionData={true}
                    handles={<></>}
                    eventDisplay={
                        <EntityFilterInfo
                            filter={getActionFilterFromFunnelStep(makeStep('Sign up', 0, 100, 100))}
                            allowWrap
                        />
                    }
                    headerAction={<LemonButton icon={<IconX />} size="xsmall" noPadding />}
                    emptyState={<span className="text-xs text-muted italic">Waiting for data...</span>}
                />
                <StepNodeShell
                    step={makeStep('First action', 2, 0, 100)}
                    stepIndex={2}
                    containerClassName="group/builder-node border-primary bg-bg-light"
                    hasConversionData={false}
                    handles={<></>}
                    eventDisplay={
                        <EntityFilterInfo
                            filter={getActionFilterFromFunnelStep(makeStep('First action', 2, 0, 100))}
                            allowWrap
                        />
                    }
                    headerAction={<LemonButton icon={<IconX />} size="xsmall" noPadding />}
                    emptyState={<span className="text-xs text-muted italic">Waiting for data...</span>}
                />
                <StepNodeShell
                    step={emptyStep}
                    stepIndex={0}
                    containerClassName="group/builder-node border-primary bg-bg-light"
                    hasConversionData={false}
                    handles={<></>}
                    eventDisplay={
                        <LemonButton type="secondary" size="small">
                            Select an event
                        </LemonButton>
                    }
                    headerAction={<LemonButton icon={<IconX />} size="xsmall" noPadding />}
                    emptyState={<span className="text-xs text-muted italic">Pick an event to see data</span>}
                />
                <StepNodeShell
                    step={makeStep('Sign up', 0, 100, 100)}
                    stepIndex={0}
                    containerClassName="group/builder-node border-primary bg-bg-light"
                    hasConversionData={true}
                    handles={<></>}
                    eventDisplay={
                        <EntityFilterInfo
                            filter={getActionFilterFromFunnelStep(makeStep('Sign up', 0, 100, 100))}
                            allowWrap
                        />
                    }
                    headerAction={<></>}
                    emptyState={<span className="text-xs text-muted italic">Waiting for data...</span>}
                />
            </div>
        </InsightProvider>
    )
}
