import type { Meta, StoryObj } from '@storybook/react'
import { createRef } from 'react'

import type { TracePreviewApi } from '../../../generated/api.schemas'
import type { CellLoads } from '../../shared/cellLoads'
import { makeTraceListItem, makeTracePreview, ready } from '../../traces/testFixtures'
import { makeErrorListItem } from '../testFixtures'
import { ErrorDrawerBody } from './ErrorDrawerBody'

const ITEM = makeErrorListItem({ changeLabel: 'was 0', changeTone: 'bad' })
const DAYS = Array.from({ length: 7 }, (_, day) => `2026-09-0${day + 1}T00:00:00Z`)
const TRACES = ['trace-1', 'trace-2', 'trace-3', 'trace-4', 'trace-5'].map((id, index) =>
    makeTraceListItem({ id, createdAt: `2026-09-07T1${index}:30:00Z` })
)
const PREVIEWS: CellLoads<TracePreviewApi> = new Map([
    ['trace-1', ready(makeTracePreview('trace-1'))],
    [
        'trace-2',
        ready(makeTracePreview('trace-2', { input: 'Summarize the attached contract in three bullet points' })),
    ],
    ['trace-3', ready(makeTracePreview('trace-3', { input: null, inputMissingReason: 'too_large' }))],
    ['trace-4', { status: 'loading' }],
    ['trace-5', { status: 'error' }],
])

const meta: Meta<typeof ErrorDrawerBody> = {
    title: 'Scenes-App/AI observability/Errors/Error drawer body',
    component: ErrorDrawerBody,
    parameters: { mockDate: '2026-09-08T09:00:00Z', testOptions: { snapshotBrowsers: [] } },
    args: {
        rect: { top: 0, right: 360, height: 900, width: 360 },
        width: 360,
        resizer: null,
        containerRef: createRef<HTMLElement>(),
        onClose: () => {},
        message: ITEM.message,
        item: ITEM,
        isNew: true,
        detail: ready({ item: ITEM, bucketStarts: DAYS, previousSeries: [0, 0, 0, 0, 0, 0, 0] }),
        recentTraces: ready(TRACES),
        previews: PREVIEWS,
        timezone: 'UTC',
        viewAllHref: '/ai-observability/traces',
        onRetry: () => {},
        onOpenTrace: () => {},
    },
}
export default meta

type Story = StoryObj<typeof ErrorDrawerBody>

export const Loaded: Story = {}

export const OpenedFromRow: Story = {
    args: { detail: { status: 'loading' }, recentTraces: { status: 'loading' }, previews: new Map() },
}

export const Failed: Story = {
    args: { item: null, detail: { status: 'error' }, recentTraces: { status: 'error' }, previews: new Map() },
}

export const NotFound: Story = {
    args: {
        message: null,
        item: null,
        detail: { status: 'not_found' },
        recentTraces: ready([]),
        previews: new Map(),
        viewAllHref: null,
    },
}
