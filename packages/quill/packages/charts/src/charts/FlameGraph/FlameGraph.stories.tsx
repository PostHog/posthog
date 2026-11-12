import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { useReactiveTheme } from '../../story-helpers'
import { CPU_PROFILE, DIFF_TREE, EDGE_CASE_TREE, LLM_TRACE } from './flame-fixtures'
import { FlameGraph } from './FlameGraph'
import type { FlameGraphProps, FlameNode } from './types'

const meta: Meta<typeof FlameGraph> = {
    title: 'Charts/FlameGraph',
    component: FlameGraph,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof FlameGraph>

const ms = (value: number): string => (value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(1)} ms`)

function Demo({
    data,
    width = 900,
    config,
    ...rest
}: Omit<FlameGraphProps, 'theme' | 'data'> & { data: FlameNode | FlameNode[]; width?: number | string }): JSX.Element {
    const theme = useReactiveTheme()
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ width }}>
            <FlameGraph data={data} theme={theme} config={{ valueFormatter: ms, ...config }} {...rest} />
        </div>
    )
}

export const CpuProfile: Story = {
    render: () => <Demo data={CPU_PROFILE} />,
}

export const CompareToBaseline: Story = {
    render: () => <Demo data={DIFF_TREE} config={{ diff: { threshold: 0.2, minCount: 10 } }} />,
}

export const LlmTrace: Story = {
    render: () => <Demo data={LLM_TRACE} />,
}

const flagFirstToolCall = (node: FlameNode): FlameNode => ({
    ...node,
    children: node.children?.map((child, index) => (index === 1 ? { ...child, color: '#f04f58' } : child)),
})

export const CustomColors: Story = {
    render: () => (
        <Demo
            data={flagFirstToolCall(LLM_TRACE)}
            config={{ groupColors: { agent: '#888888', llm: '#f7a501', tool: '#1d4aff', retrieval: '#36b37e' } }}
        />
    ),
}

export const Focused: Story = {
    render: () => (
        <Demo data={CPU_PROFILE} defaultFocusedId="handle_request/views.insights.retrieve/query_runner.run" />
    ),
}

export const Search: Story = {
    render: function Render() {
        const [query, setQuery] = useState('redis')
        return (
            <div className="flex flex-col gap-2">
                <input
                    className="w-64 border rounded px-2 py-1 text-xs"
                    value={query}
                    placeholder="Search frames"
                    onChange={(event) => setQuery(event.target.value)}
                />
                <Demo data={CPU_PROFILE} search={query} />
            </div>
        )
    },
}

export const Narrow: Story = {
    render: () => <Demo data={CPU_PROFILE} width={400} />,
}

export const EdgeCases: Story = {
    render: () => <Demo data={EDGE_CASE_TREE} />,
}

export const SeveralRoots: Story = {
    render: () => <Demo data={[CPU_PROFILE, LLM_TRACE]} />,
}

export const SingleNode: Story = {
    render: () => <Demo data={{ name: 'main', value: 42 }} />,
}

export const Empty: Story = {
    render: () => <Demo data={[]} />,
}
