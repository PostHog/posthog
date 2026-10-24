import { Meta, StoryObj } from '@storybook/react'
import { useMemo, useState } from 'react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import {
    BREAKDOWN_TREE,
    CPU_PROFILE,
    DIFF_TREE,
    EDGE_CASE_TREE,
    deepChain,
    generateFlameTree,
    LLM_TRACE,
    wideTree,
} from './flame-fixtures'
import { FlameGraph } from './FlameGraph'
import type { FlameGraphConfig, FlameGraphProps, FlameNode } from './types'

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

const compactNumber = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

/** A trend broken down by country, then browser, then OS, read as an icicle: the total on top. */
export const BreakdownIcicle: Story = {
    render: () => (
        <Demo
            data={BREAKDOWN_TREE}
            config={{ preset: 'breakdown', valueFormatter: (v) => `${compactNumber.format(v)} pageviews` }}
        />
    ),
}

export const CompareToBaseline: Story = {
    render: () => <Demo data={DIFF_TREE} config={{ diff: { threshold: 0.2, minCount: 10 } }} />,
}

export const LlmTrace: Story = {
    render: () => <Demo data={LLM_TRACE} />,
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

export const BottomUp: Story = {
    render: () => <Demo data={CPU_PROFILE} config={{ direction: 'bottom-up' }} />,
}

export const ColorByName: Story = {
    render: () => <Demo data={CPU_PROFILE} config={{ colorBy: 'name' }} />,
}

export const Narrow: Story = {
    render: () => <Demo data={CPU_PROFILE} width={400} />,
}

export const FillParent: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        const data = useMemo(() => deepChain(300), [])
        return (
            <Stage width={720} height={260}>
                <FlameGraph data={data} theme={theme} config={{ height: 'fill' }} />
            </Stage>
        )
    },
}

const PERF_CONFIG: FlameGraphConfig = { maxHeight: 640 }

/** 50,000 nodes, for profiling. Open the performance panel and click around or search. */
export const FiftyThousandNodes: Story = {
    tags: ['test-skip'],
    render: function Render() {
        const [query, setQuery] = useState('')
        const data = useMemo(() => generateFlameTree(50_000), [])
        return (
            <div className="flex flex-col gap-2">
                <input
                    className="w-64 border rounded px-2 py-1 text-xs"
                    value={query}
                    placeholder="Search frames"
                    data-attr="flame-search"
                    onChange={(event) => setQuery(event.target.value)}
                />
                <Demo data={data} width="100%" config={PERF_CONFIG} search={query} />
            </div>
        )
    },
}

export const DeepTree: Story = {
    tags: ['test-skip'],
    render: function Render() {
        const data = useMemo(() => deepChain(300), [])
        return <Demo data={data} />
    },
}

export const WideTree: Story = {
    tags: ['test-skip'],
    render: function Render() {
        const data = useMemo(() => wideTree(5000), [])
        return <Demo data={data} />
    },
}

export const EdgeCases: Story = {
    render: () => <Demo data={EDGE_CASE_TREE} config={{ colorBy: 'name' }} />,
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
