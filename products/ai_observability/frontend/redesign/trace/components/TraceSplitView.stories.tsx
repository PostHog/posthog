import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_EVALS, FIXTURE_GENERATION_MESSAGES, FIXTURE_TREE, withWidth } from '../storyFixtures'
import { TraceSplitView } from './TraceSplitView'

const generation = FIXTURE_TREE[0].children[1]

const meta: Meta<typeof TraceSplitView> = {
    title: 'Scenes-App/AI observability/Trace view/Trace split view',
    component: TraceSplitView,
    args: {
        tree: FIXTURE_TREE,
        selectedNodeId: generation.id,
        onSelectNode: () => {},
        detail: {
            node: generation,
            tab: 'messages',
            onTabChange: () => {},
            content: { kind: 'messages', messages: FIXTURE_GENERATION_MESSAGES },
            error: null,
            properties: {
                timestamp: '2026-09-01T10:15:02Z',
                model: 'gpt-4.1-mini',
                provider: 'openai',
                temperature: null,
                sessionId: null,
                promptName: null,
                promptVersion: null,
            },
            evals: { status: 'ready', results: FIXTURE_EVALS },
            raw: {},
            onViewInThread: () => {},
        },
    },
}
export default meta

type Story = StoryObj<typeof TraceSplitView>

export const Wide: Story = { decorators: [withWidth(1100)] }
export const Narrow: Story = { decorators: [withWidth(520)] }
