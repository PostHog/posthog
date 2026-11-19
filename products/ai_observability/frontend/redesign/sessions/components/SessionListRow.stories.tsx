import type { Meta, StoryObj } from '@storybook/react'

import { makeTracePersonItem, makeTracePreview, ready } from '../../traces/testFixtures'
import { makeSessionListItem } from '../testFixtures'
import { SessionListRow } from './SessionListRow'

const item = makeSessionListItem()

const meta: Meta<typeof SessionListRow> = {
    title: 'Scenes-App/AI observability/Sessions/Session list row',
    component: SessionListRow,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        item,
        title: ready(makeTracePreview(item.firstTraceId)),
        person: ready(makeTracePersonItem(item.firstTraceId).person),
        isOpen: false,
        href: '/ai-observability/sessions?session=session-1',
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-96 border rounded">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SessionListRow>

export const Ready: Story = {}

export const Open: Story = { args: { isOpen: true } }

export const Loading: Story = { args: { title: { status: 'loading' }, person: { status: 'loading' } } }

export const Untitled: Story = {
    args: { title: ready(makeTracePreview(item.firstTraceId, { input: null, inputMissingReason: null })) },
}

export const FailedCells: Story = { args: { title: { status: 'error' }, person: { status: 'error' } } }

export const SingleTurn: Story = { args: { item: makeSessionListItem({ turnCount: 1, durationMs: null }) } }
