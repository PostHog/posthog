import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { TraceNodeApi } from '../../../generated/api.schemas'
import type { TraceSearchResultsApi } from '../../../generated/api.schemas'
import { toMatchingNodeIds, toSearchBox } from '../adapter/toSearch'
import { anthropicMessagesThinkingToolUse } from '../sampleFixtures/anthropicMessagesThinkingToolUse'
import { claudeCodePluginSession } from '../sampleFixtures/claudeCodePluginSession'
import { langchainCerebrasImageError } from '../sampleFixtures/langchainCerebrasImageError'
import { openaiAgentsWithEvals } from '../sampleFixtures/openaiAgentsWithEvals'
import { SampleTraceFixture } from '../sampleFixtures/sampleTraceFixture'
import {
    FIXTURE_EVAL_OUTCOMES,
    FIXTURE_EVALS_CHIP,
    FIXTURE_FEEDBACK_MODE_WITH_SURVEYS,
    FIXTURE_SUMMARY,
    FIXTURE_TRACE,
    withWidth,
} from '../storyFixtures'
import { EvalRollupOutcome, EvalsChipData, NodeDetailTab, TraceMode } from '../types'
import { TraceView } from './TraceView'

function findNode(nodes: TraceNodeApi[], id: string): TraceNodeApi | null {
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

function markErrors(nodes: TraceNodeApi[]): TraceNodeApi[] {
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

interface PlaygroundSearch {
    query: string
    matchCounts: Record<string, number>
}

interface PlaygroundProps {
    fixture: SampleTraceFixture
    initialMode: TraceMode
    initialNodeId?: string
    evals?: EvalsChipData
    evalOutcomes?: Record<string, EvalRollupOutcome>
    search?: PlaygroundSearch
}

function searchResults(search: PlaygroundSearch): TraceSearchResultsApi {
    const matches = Object.entries(search.matchCounts).map(([nodeId, count]) => ({ nodeId, count }))
    return { total: matches.reduce((sum, match) => sum + match.count, 0), matches }
}

function Playground({
    fixture,
    initialMode,
    initialNodeId,
    evals,
    evalOutcomes = {},
    search,
}: PlaygroundProps): JSX.Element {
    const [mode, setMode] = useState<TraceMode>(initialMode)
    const [selectedNodeId, setSelectedNodeId] = useState(initialNodeId ?? fixture.initialNodeId)
    const [tab, setTab] = useState<NodeDetailTab>('messages')
    const node = findNode(fixture.tree, selectedNodeId) ?? fixture.tree[0]
    const selectAndShowSpans = (id: string): void => {
        setSelectedNodeId(id)
        setMode('spans')
    }
    const showFailingEvals = (): void => {
        selectAndShowSpans(Object.keys(evalOutcomes).find((id) => evalOutcomes[id] === 'fail') ?? fixture.tree[0].id)
        setTab('evals')
    }
    return (
        <TraceView
            status="ready"
            header={fixture.header}
            summary={{ ...fixture.summary, evals: evals ? { chip: evals, onClick: showFailingEvals } : null }}
            mode={mode}
            onModeChange={setMode}
            tree={fixture.tree}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onPrefetchNode={() => {}}
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
            evalOutcomes={evalOutcomes}
            search={
                search
                    ? {
                          ...toSearchBox(search.query, 'ready', searchResults(search), null, selectedNodeId),
                          onQueryChange: () => {},
                          onStep: () => {},
                      }
                    : null
            }
            matchingNodeIds={search ? toMatchingNodeIds(searchResults(search)) : null}
            highlightQuery={search?.query ?? null}
            summaryMode={{
                state: { status: 'ready', summary: FIXTURE_SUMMARY },
                requesting: false,
                requestError: null,
                consentGiven: true,
                onRequest: () => {},
                onRegenerate: () => {},
                onReload: () => {},
                onSelectStep: selectAndShowSpans,
            }}
            feedbackMode={FIXTURE_FEEDBACK_MODE_WITH_SURVEYS}
            feedbackCount={
                FIXTURE_FEEDBACK_MODE_WITH_SURVEYS.scores.length + FIXTURE_FEEDBACK_MODE_WITH_SURVEYS.responses.length
            }
            feedbackCountByNodeId={{ 'trace-1': 7, 'gen-answer': 2 }}
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
export const FeedbackMode: Story = { args: { fixture: FIXTURE_TRACE, initialMode: 'feedback' } }
export const Narrow: Story = {
    args: { fixture: FIXTURE_TRACE, initialMode: 'spans' },
    decorators: [withWidth(520)],
}
export const NarrowWithEvals: Story = {
    args: {
        fixture: FIXTURE_TRACE,
        initialMode: 'spans',
        evals: FIXTURE_EVALS_CHIP,
        evalOutcomes: FIXTURE_EVAL_OUTCOMES,
    },
    decorators: [withWidth(520)],
}
export const NarrowWithSearch: Story = {
    args: {
        fixture: FIXTURE_TRACE,
        initialMode: 'spans',
        search: { query: 'seats', matchCounts: { 'gen-answer': 2 } },
    },
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
