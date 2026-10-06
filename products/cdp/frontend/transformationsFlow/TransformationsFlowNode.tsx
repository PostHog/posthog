import { Handle, NodeProps, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useValues } from 'kea'

import { IconDatabase, IconFilter, IconPerson, IconPlus, IconServer } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { transformationsFlowLogic } from './transformationsFlowLogic'
import { EVENT_FILTER_MODE_TAGS, FlowNode, FlowStep, TestStepOutcome, getStepText } from './transformationsFlowUtils'

const OUTCOME_TAGS: Record<TestStepOutcome, { label: string; type: LemonTagType }> = {
    changed: { label: 'Changed', type: 'success' },
    unchanged: { label: 'No change', type: 'muted' },
    skipped: { label: 'Skipped', type: 'muted' },
    dropped: { label: 'Dropped', type: 'danger' },
    error: { label: 'Error', type: 'warning' },
    passed: { label: 'Passed', type: 'muted' },
}

function StepIcon({ step }: { step: FlowStep }): JSX.Element {
    switch (step.kind) {
        case 'capture':
            return <IconServer />
        case 'event_filtering':
            return <IconFilter />
        case 'person_processing':
            return <IconPerson />
        case 'stored':
            return <IconDatabase />
        case 'add':
            return <IconPlus />
        case 'transformation':
            return <HogFunctionIcon src={step.hogFunction?.icon_url} size="small" />
    }
}

export function TransformationsFlowNode({ data }: NodeProps<FlowNode>): JSX.Element {
    const { selectedStepId, mode, testResults, testSteps, testProgress, nextTestStep, eventFilterMode } =
        useValues(transformationsFlowLogic)
    const { step } = data
    const { title, description } = getStepText(step)

    const testStepIndex = testSteps.findIndex((testStep) => testStep.id === step.id)
    const visitedInTest = mode === 'test' && testStepIndex !== -1 && testStepIndex < testProgress
    const outcome: TestStepOutcome | null = visitedInTest ? (testResults[step.id]?.outcome ?? 'passed') : null
    const isNextTestStep = mode === 'test' && nextTestStep?.id === step.id

    const tag = outcome
        ? OUTCOME_TAGS[outcome]
        : step.kind === 'event_filtering' && eventFilterMode
          ? EVENT_FILTER_MODE_TAGS[eventFilterMode]
          : null

    return (
        <div
            className={clsx(
                // w-72 and h-16 must match FLOW_NODE_WIDTH and FLOW_NODE_HEIGHT, because React Flow lays out the nodes with those sizes.
                'flex items-center gap-2 w-72 h-16 px-3 rounded border bg-surface-primary cursor-pointer transition-colors',
                step.kind === 'add' && 'border-dashed text-secondary',
                selectedStepId === step.id || isNextTestStep ? 'border-accent' : 'border-primary',
                isNextTestStep && 'border-2',
                mode === 'test' && step.kind === 'add' && 'opacity-50'
            )}
            data-attr={`transformations-flow-node-${step.kind}`}
        >
            {/* Edges attach to these handles. They are not for user connections. */}
            <Handle type="target" position={Position.Top} className="opacity-0" isConnectable={false} />
            <div className="flex items-center justify-center shrink-0 size-8 rounded bg-surface-secondary text-lg">
                <StepIcon step={step} />
            </div>
            <div className="flex flex-col min-w-0 flex-1">
                <span className="font-semibold truncate">{title}</span>
                <span className="text-xs text-secondary truncate">{description}</span>
            </div>
            {tag && (
                <LemonTag type={tag.type} size="small" className="shrink-0">
                    {tag.label}
                </LemonTag>
            )}
            <Handle type="source" position={Position.Bottom} className="opacity-0" isConnectable={false} />
        </div>
    )
}
