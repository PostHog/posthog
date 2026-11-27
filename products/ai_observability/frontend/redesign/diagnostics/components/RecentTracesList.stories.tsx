import type { Meta, StoryObj } from '@storybook/react'

import type { TracePreviewApi } from '../../../generated/api.schemas'
import type { CellLoads } from '../../shared/cellLoads'
import { withWidth } from '../../trace/storyFixtures'
import { makeTraceListItem, makeTracePreview, ready } from '../../traces/testFixtures'
import { RecentTracesList } from './RecentTracesList'

const TRACES = ['trace-1', 'trace-2', 'trace-3', 'trace-4'].map((id, index) =>
    makeTraceListItem({ id, createdAt: `2026-09-07T1${index}:30:00Z` })
)
const PREVIEWS: CellLoads<TracePreviewApi> = new Map([
    ['trace-1', ready(makeTracePreview('trace-1'))],
    ['trace-2', ready(makeTracePreview('trace-2', { input: null, inputMissingReason: 'too_large' }))],
    ['trace-3', { status: 'loading' }],
    ['trace-4', { status: 'error' }],
])

const meta: Meta<typeof RecentTracesList> = {
    title: 'Scenes-App/AI observability/Diagnostics/Recent traces list',
    component: RecentTracesList,
    parameters: { mockDate: '2026-09-08T09:00:00Z', testOptions: { snapshotBrowsers: [] } },
    args: {
        traces: ready(TRACES),
        previews: PREVIEWS,
        emptyMessage: 'No traces that called this tool match the filters.',
        inputFailedMessage: "Couldn't load the input. Reopen the tool to try again.",
        onRetry: () => {},
        onOpenTrace: () => {},
        'data-attr': 'tool-drawer',
    },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof RecentTracesList>

export const Loaded: Story = {}
