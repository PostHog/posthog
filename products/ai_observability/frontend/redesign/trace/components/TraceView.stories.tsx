import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { anthropicMessagesThinkingToolUse } from '../sampleFixtures/anthropicMessagesThinkingToolUse'
import { claudeCodePluginSession } from '../sampleFixtures/claudeCodePluginSession'
import { langchainCerebrasImageError } from '../sampleFixtures/langchainCerebrasImageError'
import { openaiAgentsWithEvals } from '../sampleFixtures/openaiAgentsWithEvals'
import { SampleTraceFixture } from '../sampleFixtures/sampleTraceFixture'
import { FIXTURE_TRACE, withWidth } from '../storyFixtures'
import { NodeDetailTab, TraceMode, TraceTreeNode } from '../types'
import { TraceView } from './TraceView'

function findNode(nodes: TraceTreeNode[], id: string): TraceTreeNode | null {
    for (const node of nodes) {
        if (node.id === id) {
            return node
        }
        const found = findNode(node.children, id)
        if (found) {
            return found
        }
    }
    return null
}

const ERRORED_NODE_IDS = new Set(['trace-1', 'gen-answer'])

function markErrors(nodes: TraceTreeNode[]): TraceTreeNode[] {
    return nodes.map((node) => ({
        ...node,
        hasError: ERRORED_NODE_IDS.has(node.id),
        children: markErrors(node.children),
    }))
}

const FIXTURE_ERROR_TRACE: SampleTraceFixture = {
    ...FIXTURE_TRACE,
    header: { ...FIXTURE_TRACE.header, hasError: true },
    tree: markErrors(FIXTURE_TRACE.tree),
    details: {
        ...FIXTURE_TRACE.details,
        'gen-answer': { ...FIXTURE_TRACE.details['gen-answer'], error: 'RateLimitError: 429 Too Many Requests' },
    },
}

interface PlaygroundProps {
    fixture: SampleTraceFixture
    initialMode: TraceMode
    initialNodeId?: string
}

function Playground({ fixture, initialMode, initialNodeId }: PlaygroundProps): JSX.Element {
    const [mode, setMode] = useState<TraceMode>(initialMode)
    const [selectedNodeId, setSelectedNodeId] = useState(initialNodeId ?? fixture.initialNodeId)
    const [tab, setTab] = useState<NodeDetailTab>('messages')
    const node = findNode(fixture.tree, selectedNodeId) ?? fixture.tree[0]
    const selectAndShowSpans = (id: string): void => {
        setSelectedNodeId(id)
        setMode('spans')
    }
    return (
        <TraceView
            status="ready"
            header={fixture.header}
            summary={fixture.summary}
            mode={mode}
            onModeChange={setMode}
            tree={fixture.tree}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onSelectFromView={selectAndShowSpans}
            detail={{
                ...fixture.details[node.id],
                node,
                tab,
                onTabChange: setTab,
                onViewInThread: node.kind === 'generation' ? () => setMode('thread') : null,
            }}
            thread={fixture.thread}
            timeline={fixture.timeline}
        />
    )
}

const meta: Meta<typeof Playground> = {
    title: 'Scenes-App/AI observability/Trace view/Trace view',
    component: Playground,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof Playground>

export const SpanSelected: Story = {
    args: { fixture: FIXTURE_TRACE, initialMode: 'spans', initialNodeId: 'span-retrieve' },
}
export const GenerationSelected: Story = { args: { fixture: FIXTURE_TRACE, initialMode: 'spans' } }
export const ErrorTrace: Story = { args: { fixture: FIXTURE_ERROR_TRACE, initialMode: 'spans' } }
export const ThreadMode: Story = { args: { fixture: FIXTURE_TRACE, initialMode: 'thread' } }
export const TimelineMode: Story = { args: { fixture: FIXTURE_TRACE, initialMode: 'timeline' } }
export const Narrow: Story = {
    args: { fixture: FIXTURE_TRACE, initialMode: 'spans' },
    decorators: [withWidth(520)],
}
export const SampleAnthropicThinkingToolUse: Story = {
    args: { fixture: anthropicMessagesThinkingToolUse, initialMode: 'spans' },
}
export const SampleClaudeCodeSession: Story = { args: { fixture: claudeCodePluginSession, initialMode: 'spans' } }
export const SampleLangChainImageError: Story = {
    args: { fixture: langchainCerebrasImageError, initialMode: 'spans' },
}
export const SampleOpenAIAgentsWithEvals: Story = {
    args: { fixture: openaiAgentsWithEvals, initialMode: 'spans' },
}
export const Loading: StoryObj<typeof TraceView> = {
    render: () => <TraceView status="loading" />,
    decorators: [withWidth(1100)],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const LoadError: StoryObj<typeof TraceView> = {
    render: () => (
        <TraceView
            status="error"
            errorMessage="This trace is outside the loaded time range."
            backLink={{ label: 'Back to traces', href: '/traces' }}
        />
    ),
}
