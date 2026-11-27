import type { Meta, StoryObj } from '@storybook/react'
import { createRef } from 'react'

import type { TraceListItemApi } from '../../../generated/api.schemas'
import { makeTraceListItem, ready } from '../../traces/testFixtures'
import { makeToolDetail, makeToolListItem } from '../testFixtures'
import { ToolDrawerBody } from './ToolDrawerBody'

const ITEM = makeToolListItem()
const traces = (ids: string[]): TraceListItemApi[] =>
    ids.map((id, index) => makeTraceListItem({ id, createdAt: `2026-09-07T1${index}:30:00Z` }))
const meta: Meta<typeof ToolDrawerBody> = {
    title: 'Scenes-App/AI observability/Tools/Tool drawer body',
    component: ToolDrawerBody,
    parameters: { mockDate: '2026-09-08T09:00:00Z', testOptions: { snapshotBrowsers: [] } },
    args: {
        rect: { top: 0, right: 360, height: 900, width: 360 },
        width: 360,
        resizer: null,
        containerRef: createRef<HTMLElement>(),
        onClose: () => {},
        name: ITEM.name,
        item: ITEM,
        detail: ready(makeToolDetail()),
        showsFailures: true,
        recentFailures: ready(traces(['failed-1'])),
        recentCalls: ready(traces(['call-1', 'call-2'])),
        previews: new Map(),
        timezone: 'UTC',
        viewAllHref: '/ai-observability/traces',
        onRetry: () => {},
        onOpenTrace: () => {},
    },
}
export default meta

type Story = StoryObj<typeof ToolDrawerBody>

export const Loaded: Story = {}
