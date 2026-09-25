import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import {
    FIXTURE_EVALS,
    FIXTURE_GENERATION_MESSAGES,
    FIXTURE_STATS,
    FIXTURE_TIMELINE_ROWS,
    FIXTURE_TREE,
    FIXTURE_TURN,
    withWidth,
} from '../storyFixtures'
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

interface PlaygroundProps {
    initialMode: TraceMode
    initialNodeId: string
    hasError?: boolean
}

const ERRORED_NODE_IDS = new Set(['trace-1', 'gen-answer'])

function markErrors(nodes: TraceTreeNode[]): TraceTreeNode[] {
    return nodes.map((node) => ({
        ...node,
        hasError: ERRORED_NODE_IDS.has(node.id),
        children: markErrors(node.children),
    }))
}

function Playground({ initialMode, initialNodeId, hasError = false }: PlaygroundProps): JSX.Element {
    const [mode, setMode] = useState<TraceMode>(initialMode)
    const [selectedNodeId, setSelectedNodeId] = useState(initialNodeId)
    const [tab, setTab] = useState<NodeDetailTab>('messages')
    const tree = hasError ? markErrors(FIXTURE_TREE) : FIXTURE_TREE
    const node = findNode(tree, selectedNodeId) ?? tree[0]
    const selectAndShowSpans = (id: string): void => {
        setSelectedNodeId(id)
        setMode('spans')
    }
    return (
        <TraceView
            status="ready"
            header={{
                name: 'answer-billing-question',
                hasError,
                olderHref: '/older',
                newerHref: '/newer',
                backHref: '/traces',
            }}
            summary={{
                traceId: '3f9c2a71-5b8e-4d0f-a1c2-7e6d5b4a3c21',
                timestamp: '2026-09-01T10:15:00Z',
                person: { label: 'ana@example.com', href: '/person/ana' },
                totals: FIXTURE_STATS,
            }}
            mode={mode}
            onModeChange={setMode}
            tree={tree}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onSelectFromView={selectAndShowSpans}
            detail={{
                node,
                tab,
                onTabChange: setTab,
                content:
                    node.kind === 'generation'
                        ? { kind: 'messages', messages: FIXTURE_GENERATION_MESSAGES }
                        : { kind: 'io', input: { question: 'Why did my invoice go up?' }, output: { hits: 3 } },
                error: hasError && node.kind === 'generation' ? 'RateLimitError: 429 Too Many Requests' : null,
                properties: {
                    timestamp: '2026-09-01T10:15:02Z',
                    model: node.model,
                    provider: node.model ? 'openai' : null,
                    temperature: null,
                    sessionId: 'sess-7f3a',
                    promptName: null,
                    promptVersion: null,
                },
                evals: { status: 'ready', results: node.kind === 'generation' ? FIXTURE_EVALS : [] },
                raw: { id: node.id, kind: node.kind },
                onViewInThread: node.kind === 'generation' ? () => setMode('thread') : null,
            }}
            thread={{ turns: [FIXTURE_TURN], activeTurnId: FIXTURE_TURN.id }}
            timeline={{ rows: FIXTURE_TIMELINE_ROWS, totalMs: 2310 }}
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

export const SpanSelected: Story = { args: { initialMode: 'spans', initialNodeId: 'span-retrieve' } }
export const GenerationSelected: Story = { args: { initialMode: 'spans', initialNodeId: 'gen-answer' } }
export const ErrorTrace: Story = { args: { initialMode: 'spans', initialNodeId: 'gen-answer', hasError: true } }
export const ThreadMode: Story = { args: { initialMode: 'thread', initialNodeId: 'trace-1' } }
export const TimelineMode: Story = { args: { initialMode: 'timeline', initialNodeId: 'gen-answer' } }
export const Narrow: Story = {
    args: { initialMode: 'spans', initialNodeId: 'gen-answer' },
    decorators: [withWidth(520)],
}
export const Loading: StoryObj<typeof TraceView> = { render: () => <TraceView status="loading" /> }
export const LoadError: StoryObj<typeof TraceView> = {
    render: () => (
        <TraceView status="error" errorMessage="This trace is outside the loaded time range." backHref="/traces" />
    ),
}
