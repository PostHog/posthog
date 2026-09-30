import type { Meta, StoryObj } from '@storybook/react'

import {
    FIXTURE_EVALS,
    FIXTURE_GENERATION_INPUT,
    FIXTURE_GENERATION_OUTPUT,
    FIXTURE_GENERATION_PROPERTIES,
    FIXTURE_TREE,
    withWidth,
} from '../storyFixtures'
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
            content: { kind: 'messages', input: FIXTURE_GENERATION_INPUT, output: FIXTURE_GENERATION_OUTPUT },
            error: null,
            properties: FIXTURE_GENERATION_PROPERTIES,
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
