import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { langchainCerebrasImageError } from '../sampleFixtures/langchainCerebrasImageError'
import {
    FIXTURE_EVALS,
    FIXTURE_GENERATION_INPUT,
    FIXTURE_GENERATION_OUTPUT,
    FIXTURE_GENERATION_PROPERTIES,
    FIXTURE_SPAN_PROPERTIES,
    FIXTURE_TREE,
    withWidth,
} from '../storyFixtures'
import { NodeDetailTab } from '../types'
import { NodeDetail, NodeDetailProps } from './NodeDetail'

const generation = FIXTURE_TREE[0].children[1]
const span = FIXTURE_TREE[0].children[0]

const base: Omit<NodeDetailProps, 'tab' | 'onTabChange'> = {
    node: generation,
    content: { kind: 'messages', input: FIXTURE_GENERATION_INPUT, output: FIXTURE_GENERATION_OUTPUT },
    error: null,
    properties: FIXTURE_GENERATION_PROPERTIES,
    evals: { status: 'ready', results: FIXTURE_EVALS },
    raw: { event: '$ai_generation', id: 'gen-answer' },
    onViewInThread: () => {},
}

const failedGeneration = langchainCerebrasImageError.tree[0].children[0].children[0]

function Stateful(props: Omit<NodeDetailProps, 'tab' | 'onTabChange'> & { initialTab?: NodeDetailTab }): JSX.Element {
    const [tab, setTab] = useState<NodeDetailTab>(props.initialTab ?? 'messages')
    return <NodeDetail {...props} tab={tab} onTabChange={setTab} />
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
        content: { kind: 'io', input: { query: 'invoice went up' }, output: { hits: 3 } },
        properties: FIXTURE_SPAN_PROPERTIES,
        onViewInThread: null,
    },
}
export const GenerationDetailsTab: Story = { args: { ...base, initialTab: 'details' } }
export const SpanDetailsTab: Story = {
    args: { ...base, node: span, properties: FIXTURE_SPAN_PROPERTIES, onViewInThread: null, initialTab: 'details' },
}
export const LoadingContent: Story = { args: { ...base, content: { kind: 'loading' } } }
export const ContentLoadError: Story = {
    args: { ...base, content: { kind: 'error', message: 'This step could not be loaded. Try again later.' } },
}
export const WithError: Story = {
    args: {
        ...base,
        node: { ...generation, hasError: true },
        error: 'RateLimitError: 429 Too Many Requests',
        content: { kind: 'messages', input: FIXTURE_GENERATION_INPUT.slice(0, 2), output: [] },
    },
}
export const NothingCaptured: Story = { args: { ...base, content: { kind: 'messages', input: [], output: [] } } }
export const EvalsTab: Story = { args: { ...base, initialTab: 'evals' } }
export const EvalsLoadError: Story = {
    args: {
        ...base,
        initialTab: 'evals',
        evals: { status: 'error', errorMessage: 'Evaluation results could not be loaded. Try again later.' },
    },
}
export const Narrow: Story = { args: base, decorators: [withWidth(520)] }
export const FailedGenerationWithImage: Story = {
    args: {
        ...langchainCerebrasImageError.details[failedGeneration.id],
        node: failedGeneration,
        onViewInThread: () => {},
    },
}
