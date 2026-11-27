import type { Meta, StoryObj } from '@storybook/react'
import { createRef } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { KpiTileSparkline } from '../../home/components/KpiTileSparkline'
import { EntityDrawer } from './EntityDrawer'

const SCENE_TOP = 56
const SCENE_HEIGHT = 720
const WIDE_SCENE = 1200
const NARROW_SCENE = 800

function sceneRect(width: number): { top: number; right: number; height: number; width: number } {
    return { top: SCENE_TOP, right: window.innerWidth, height: SCENE_HEIGHT, width }
}

function RecentRows({ rows }: { rows: [string, string][] }): JSX.Element {
    return (
        <ul className="m-0 flex list-none flex-col divide-y rounded border p-0">
            {rows.map(([preview, time]) => (
                <li key={preview} className="flex min-w-0 items-center justify-between gap-3 px-3 py-2 text-sm">
                    <span className="truncate">{preview}</span>
                    <span className="shrink-0 text-xs text-secondary">{time}</span>
                </li>
            ))}
        </ul>
    )
}

function WeekChart({ note }: { note: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 rounded border p-3">
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium text-secondary">Last 7 days</span>
                <span className="text-xs text-secondary">{note}</span>
            </div>
            <div className="h-8">
                <KpiTileSparkline series={[4, 6, 5, 9, 12, 14, 18]} />
            </div>
        </div>
    )
}

function ViewTraces(): JSX.Element {
    return (
        <LemonButton type="secondary" size="small" sideIcon={<IconArrowRight />}>
            View traces
        </LemonButton>
    )
}

const RECENT_TRACES: [string, string][] = [
    ['Summarize the attached meeting notes into three bullet points', 'Nov 24, 14:02'],
    ['What is the refund window for annual plans?', 'Nov 24, 13:47'],
    ['Translate this paragraph into Spanish and keep the formatting', 'Nov 24, 11:15'],
]

const meta: Meta<typeof EntityDrawer> = {
    title: 'Scenes-App/AI observability/Shared/Entity drawer',
    component: EntityDrawer,
    parameters: { testOptions: { snapshotTargetSelector: 'aside', skipCanvasDraw: true } },
    args: {
        'aria-label': 'Error detail',
        'data-attr': 'error-drawer',
        rect: sceneRect(WIDE_SCENE),
        width: 360,
        resizer: null,
        containerRef: createRef<HTMLElement>(),
        onClose: () => {},
        title: <span className="font-mono">RateLimitError: too many requests, retry after 20s</span>,
        tag: <LemonTag type="danger">Increasing</LemonTag>,
        tiles: [
            { label: 'Occurrences', value: '1,284' },
            { label: 'Traces', value: '312' },
            { label: 'Users', value: '87' },
            { label: 'First seen', value: 'Nov 12, 2026' },
        ],
        chart: <WeekChart note="Up 40% on the previous 7 days" />,
        sections: [{ title: 'Recent traces', content: <RecentRows rows={RECENT_TRACES} /> }],
        footer: <ViewTraces />,
    },
}
export default meta

type Story = StoryObj<typeof EntityDrawer>

export const ErrorDrawer: Story = {}

export const ErrorDrawerFullWidth: Story = {
    args: { rect: sceneRect(NARROW_SCENE) },
}

export const ToolDrawer: Story = {
    args: {
        'aria-label': 'Tool detail',
        'data-attr': 'tool-drawer',
        title: <span className="font-mono">search_knowledge_base</span>,
        tag: <LemonTag type="muted">tool</LemonTag>,
        tiles: [
            { label: 'Calls', value: '9,410' },
            { label: 'Failure rate', value: '6.2%' },
            { label: 'Traces', value: '2,033' },
        ],
        chart: <WeekChart note="Down 12% on the previous 7 days" />,
        sections: [
            { title: 'Recent traces', content: <RecentRows rows={RECENT_TRACES} /> },
            { title: 'Recent failures', content: null },
        ],
    },
}

export const PersonDrawer: Story = {
    args: {
        'aria-label': 'Person detail',
        'data-attr': 'person-drawer',
        rect: sceneRect(NARROW_SCENE),
        title: 'jordan@example.com',
        tag: undefined,
        tiles: [
            { label: 'Traces', value: '146' },
            { label: 'Sessions', value: '23' },
            { label: 'Cost', value: '$4.18' },
            { label: 'Last seen', value: 'Nov 24, 2026' },
        ],
        chart: undefined,
        sections: [
            { title: 'Recent traces', content: <RecentRows rows={RECENT_TRACES} /> },
            {
                title: 'Recent sessions',
                content: (
                    <RecentRows
                        rows={[
                            ['Onboarding assistant, 6 traces', 'Nov 24, 13:40'],
                            ['Support chat, 3 traces', 'Nov 23, 09:12'],
                        ]}
                    />
                ),
            },
        ],
    },
}

export const Loading: Story = {
    args: {
        tiles: [
            { label: 'Occurrences', value: null, loading: true },
            { label: 'Traces', value: null, loading: true },
            { label: 'Users', value: null, loading: true },
            { label: 'First seen', value: null, loading: true },
        ],
        chart: undefined,
        sections: [{ title: 'Recent traces', content: <LemonSkeleton repeat={3} className="h-8" /> }],
    },
}
