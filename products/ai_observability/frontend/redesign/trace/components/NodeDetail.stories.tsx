import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconDatabase } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { TraceNodeContentApi } from '../../../generated/api.schemas'
import { langchainCerebrasImageError } from '../sampleFixtures/langchainCerebrasImageError'
import { jsonContent, messagesContent } from '../sampleFixtures/sampleContent'
import { sampleRaw } from '../sampleFixtures/sampleTraceFixture'
import {
    FIXTURE_GENERATION_INPUT,
    FIXTURE_GENERATION_OUTPUT,
    FIXTURE_LONG_AGENT_INPUT,
    FIXTURE_LONG_AGENT_OUTPUT,
    FIXTURE_LONG_ANSWER_MESSAGE,
    FIXTURE_STEP_FEEDBACK,
    FIXTURE_TRACE,
    FIXTURE_TREE,
    fixtureGenerationDetail,
    fixtureSpanDetail,
    withStepScroller,
    withWidth,
} from '../storyFixtures'
import { stepLabelsOf } from '../traceTreeLookups'
import { MessagesOpening, NodeDetailTab, NodeLoad } from '../types'
import { NodeDetail, NodeDetailProps } from './NodeDetail'

const generation = FIXTURE_TREE[0].children[1]
const span = FIXTURE_TREE[0].children[0]

const generationContent = messagesContent(FIXTURE_GENERATION_INPUT, FIXTURE_GENERATION_OUTPUT)

function generationLoad(content: TraceNodeContentApi, error: string | null = null): NodeLoad {
    return fixtureGenerationDetail(content, error).load
}

function spanLoad(content: TraceNodeContentApi): NodeLoad {
    return fixtureSpanDetail(content).load
}

const base: Omit<NodeDetailProps, 'tab' | 'onTabChange' | 'messagesOpening' | 'onMessagesOpeningChange'> = {
    node: generation,
    load: generationLoad(generationContent),
    trace: FIXTURE_TRACE.trace,
    evaluationResults: FIXTURE_TRACE.evaluationResults,
    evaluationResultsFailed: false,
    stepLabels: stepLabelsOf(FIXTURE_TREE),
    raw: sampleRaw('generation', generation.id, {
        name: '$ai_generation',
        timestamp: '2026-09-01T10:15:02Z',
        properties: { $ai_model: 'gpt-4.1-mini', $ai_provider: 'openai', $ai_input_tokens: 1822 },
    }),
    onViewInThread: () => {},
    onSelectNode: () => {},
}

const failedGeneration = langchainCerebrasImageError.tree[0].children[0].children[0]

function Stateful(
    props: Omit<NodeDetailProps, 'tab' | 'onTabChange' | 'messagesOpening' | 'onMessagesOpeningChange'> & {
        initialTab?: NodeDetailTab
    }
): JSX.Element {
    const [tab, setTab] = useState<NodeDetailTab>(props.initialTab ?? 'messages')
    const [opening, setOpening] = useState<MessagesOpening>('lastTurn')
    return (
        <NodeDetail
            {...props}
            tab={tab}
            onTabChange={setTab}
            messagesOpening={opening}
            onMessagesOpeningChange={setOpening}
        />
    )
}

const meta: Meta<typeof Stateful> = {
    title: 'Scenes-App/AI observability/Trace view/Node detail',
    component: Stateful,
}
export default meta

type Story = StoryObj<typeof Stateful>

export const Generation: Story = { args: base }
export const SpanInputOutput: Story = {
    args: {
        ...base,
        node: span,
        load: spanLoad(jsonContent({ query: 'invoice went up' }, { hits: 3 })),
        onViewInThread: null,
    },
}
const mixedStepContent: TraceNodeContentApi = {
    input: { kind: 'json', value: { question: 'Why did my invoice go up?', account_id: 'acct_42' } },
    output: { kind: 'messages', messages: FIXTURE_GENERATION_OUTPUT },
}
export const MixedStep: Story = {
    args: { ...base, node: span, load: spanLoad(mixedStepContent), onViewInThread: null },
}
export const MixedStepNarrow: Story = { args: MixedStep.args, decorators: [withWidth(380)] }
export const GenerationDetailsTab: Story = { args: { ...base, initialTab: 'details' } }
export const SpanDetailsTab: Story = {
    args: { ...base, node: span, load: spanLoad(generationContent), onViewInThread: null, initialTab: 'details' },
}
export const LoadingContent: Story = {
    args: { ...base, load: { status: 'loading' } },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const ContentLoadError: Story = {
    args: { ...base, load: { status: 'error', failure: 'failed' } },
}
export const ContentNotFound: Story = {
    args: { ...base, load: { status: 'error', failure: 'not_found' } },
}
export const DetailsTabWhileLoading: Story = {
    args: { ...base, load: { status: 'loading' }, initialTab: 'details' },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const WithError: Story = {
    args: {
        ...base,
        node: { ...generation, hasError: true },
        load: generationLoad(
            messagesContent(FIXTURE_GENERATION_INPUT.slice(0, 2), []),
            'RateLimitError: 429 Too Many Requests'
        ),
    },
}
export const NothingCaptured: Story = { args: { ...base, load: generationLoad(messagesContent([], [])) } }
export const RawTab: Story = {
    args: { ...base, initialTab: 'raw' },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export const EvalsTab: Story = { args: { ...base, initialTab: 'evals' } }
export const EvalsLoadError: Story = {
    args: {
        ...base,
        initialTab: 'evals',
        evaluationResults: null,
        evaluationResultsFailed: true,
    },
}
export const LongConversation: Story = {
    args: {
        ...base,
        load: generationLoad(messagesContent(FIXTURE_LONG_AGENT_INPUT, FIXTURE_LONG_AGENT_OUTPUT)),
    },
    decorators: [withStepScroller],
}
export const Narrow: Story = { args: base, decorators: [withWidth(520)] }
export const NarrowWithActions: Story = {
    args: {
        ...base,
        node: { ...generation, name: 'answer-billing-question-with-retrieved-context-and-follow-up' },
        actions: (
            <LemonButton type="secondary" size="xsmall" icon={<IconDatabase />}>
                Add to dataset
            </LemonButton>
        ),
    },
    decorators: [withWidth(520)],
}
export const FailedGenerationWithImage: Story = {
    args: {
        ...langchainCerebrasImageError.details[failedGeneration.id],
        node: failedGeneration,
        trace: langchainCerebrasImageError.trace,
        evaluationResults: langchainCerebrasImageError.evaluationResults,
        evaluationResultsFailed: false,
        stepLabels: stepLabelsOf(langchainCerebrasImageError.tree),
        onViewInThread: () => {},
        onSelectNode: () => {},
    },
}
export const WithFeedback: Story = {
    args: { ...base, stepFeedback: { feedback: FIXTURE_STEP_FEEDBACK, onOpen: () => {} } },
    decorators: [withWidth(520)],
}
export const LongMessage: Story = {
    args: {
        ...base,
        load: generationLoad(messagesContent(FIXTURE_GENERATION_INPUT, [FIXTURE_LONG_ANSWER_MESSAGE])),
    },
    decorators: [withStepScroller],
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
