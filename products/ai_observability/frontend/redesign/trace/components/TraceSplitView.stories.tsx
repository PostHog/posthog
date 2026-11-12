import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_TRACE, FIXTURE_TREE, withWidth } from '../storyFixtures'
import { stepLabelsOf } from '../traceTreeLookups'
import { TraceSplitView } from './TraceSplitView'

const generation = FIXTURE_TREE[0].children[1]

const meta: Meta<typeof TraceSplitView> = {
    title: 'Scenes-App/AI observability/Trace view/Trace split view',
    component: TraceSplitView,
    args: {
        tree: FIXTURE_TREE,
        selectedNodeId: generation.id,
        onSelectNode: () => {},
        onPrefetchNode: () => {},
        evalOutcomes: new Map(),
        detail: {
            node: generation,
            tab: 'messages',
            onTabChange: () => {},
            messagesOpening: 'lastTurn',
            onMessagesOpeningChange: () => {},
            load: FIXTURE_TRACE.details[generation.id].load,
            trace: FIXTURE_TRACE.trace,
            evaluationResults: FIXTURE_TRACE.evaluationResults,
            evaluationResultsFailed: false,
            stepLabels: stepLabelsOf(FIXTURE_TREE),
            raw: undefined,
            onViewInThread: () => {},
        },
    },
}
export default meta

type Story = StoryObj<typeof TraceSplitView>

export const Wide: Story = { decorators: [withWidth(1100)] }
export const Narrow: Story = { decorators: [withWidth(520)] }
