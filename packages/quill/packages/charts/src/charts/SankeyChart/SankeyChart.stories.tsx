import { Meta, StoryObj } from '@storybook/react'

import { playHoverAtFraction, Stage, useReactiveTheme } from '../../story-helpers'
import type { SankeyLinkInput, SankeyNodeInput } from './sankey-data'
import { SankeyChart } from './SankeyChart'

// Agent sessions through an MCP server: which tool ran first, what came next, and how the
// session ended. The same tool appears in several stages, so each stage gets its own node id
// while nodes that share a label share a color.
const STAGES = ['Start', 'First tool', 'Second tool', 'Outcome']

const NODES: SankeyNodeInput[] = [
    { id: 'start', label: 'Sessions' },
    { id: '1:schema', label: 'read-data-schema' },
    { id: '1:sql', label: 'execute-sql' },
    { id: '1:trends', label: 'query-trends' },
    { id: '2:sql', label: 'execute-sql' },
    { id: '2:trends', label: 'query-trends' },
    { id: '2:insight', label: 'insight-create' },
    { id: '2:ended', label: 'Ended' },
    { id: 'completed', label: 'Completed', color: 'var(--data-color-3)' },
    { id: 'error', label: 'Error', color: 'var(--data-color-5)' },
]

const LINKS: SankeyLinkInput[] = [
    { source: 'start', target: '1:schema', value: 54 },
    { source: 'start', target: '1:sql', value: 31 },
    { source: 'start', target: '1:trends', value: 15 },
    { source: '1:schema', target: '2:sql', value: 38 },
    { source: '1:schema', target: '2:trends', value: 16 },
    { source: '1:sql', target: '2:sql', value: 22 },
    { source: '1:sql', target: '2:ended', value: 9 },
    { source: '1:trends', target: '2:insight', value: 11 },
    { source: '1:trends', target: '2:ended', value: 4 },
    { source: '2:sql', target: 'completed', value: 47 },
    { source: '2:sql', target: 'error', value: 13, color: 'var(--data-color-5)' },
    { source: '2:trends', target: 'completed', value: 16 },
    { source: '2:insight', target: 'completed', value: 11 },
    { source: '2:ended', target: 'error', value: 13, color: 'var(--data-color-5)' },
]

const meta: Meta<typeof SankeyChart> = {
    title: 'Charts/SankeyChart',
    component: SankeyChart,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof SankeyChart>

export const ToolCallJourneys: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={320}>
                <SankeyChart nodes={NODES} links={LINKS} theme={theme} config={{ columnLabels: STAGES }} />
            </Stage>
        )
    },
}

export const HoveredLink: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={320}>
                <SankeyChart nodes={NODES} links={LINKS} theme={theme} config={{ columnLabels: STAGES }} />
            </Stage>
        )
    },
    play: async ({ canvasElement }) => {
        await playHoverAtFraction(canvasElement, 0.2, 0.3)
    },
}

export const LeftAlignedWithValues: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={320}>
                <SankeyChart
                    nodes={NODES}
                    links={LINKS}
                    theme={theme}
                    config={{ nodeAlign: 'left', showNodeValues: true, preserveNodeOrder: true, linkOpacity: 0.25 }}
                />
            </Stage>
        )
    },
}

// The host decides what emphasis means: here every session that reached execute-sql at the
// second stage, upstream and downstream, while the chart's own hover dimming stays off.
const SQL_PATH_HIGHLIGHT = {
    nodeIds: new Set(['start', '1:schema', '1:sql', '2:sql', 'completed', 'error']),
    linkIndices: new Set([0, 1, 3, 5, 9, 10]),
}

export const ControlledHighlight: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={320}>
                <SankeyChart
                    nodes={NODES}
                    links={LINKS}
                    theme={theme}
                    config={{ columnLabels: STAGES }}
                    highlight={SQL_PATH_HIGHLIGHT}
                />
            </Stage>
        )
    },
}

export const Narrow: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={360} height={240}>
                <SankeyChart nodes={NODES} links={LINKS} theme={theme} config={{ columnLabels: STAGES }} />
            </Stage>
        )
    },
}
