import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FIXTURE_EVALS, FIXTURE_GENERATION_MESSAGES, FIXTURE_TREE, withWidth } from '../storyFixtures'
import { NodeDetailTab } from '../types'
import { NodeDetail, NodeDetailProps } from './NodeDetail'

const generation = FIXTURE_TREE[0].children[1]
const span = FIXTURE_TREE[0].children[0]

const base: Omit<NodeDetailProps, 'tab' | 'onTabChange'> = {
    node: generation,
    content: { kind: 'messages', messages: FIXTURE_GENERATION_MESSAGES },
    error: null,
    properties: {
        timestamp: '2026-09-01T10:15:02Z',
        model: 'gpt-4.1-mini',
        provider: 'openai',
        temperature: 0.2,
        sessionId: 'sess-7f3a',
        promptName: null,
        promptVersion: null,
    },
    evals: { status: 'ready', results: FIXTURE_EVALS },
    raw: { event: '$ai_generation', id: 'gen-answer' },
    onViewInThread: () => {},
}

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
        onViewInThread: null,
    },
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
        content: { kind: 'messages', messages: FIXTURE_GENERATION_MESSAGES.slice(0, 2) },
    },
}
export const EvalsTab: Story = { args: { ...base, initialTab: 'evals' } }
export const EvalsLoadError: Story = {
    args: {
        ...base,
        initialTab: 'evals',
        evals: { status: 'error', errorMessage: 'Evaluation results could not be loaded. Try again later.' },
    },
}
export const Narrow: Story = { args: base, decorators: [withWidth(420)] }
