import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FIXTURE_TREE, withWidth } from '../storyFixtures'
import { TraceTreeNode } from '../types'
import { TraceTree } from './TraceTree'

function Stateful({ nodes }: { nodes: TraceTreeNode[] }): JSX.Element {
    const [selected, setSelected] = useState<string | null>('gen-answer')
    return <TraceTree nodes={nodes} selectedNodeId={selected} onSelectNode={setSelected} />
}

const meta: Meta<typeof Stateful> = {
    title: 'Scenes-App/AI observability/Trace view/Trace tree',
    component: Stateful,
    decorators: [withWidth(280)],
}
export default meta

type Story = StoryObj<typeof Stateful>

export const Default: Story = { args: { nodes: FIXTURE_TREE } }
export const WithError: Story = {
    args: {
        nodes: [
            {
                ...FIXTURE_TREE[0],
                hasError: true,
                children: [{ ...FIXTURE_TREE[0].children[1], hasError: true }],
            },
        ],
    },
}
