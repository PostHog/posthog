import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_STATS, withWidth } from '../storyFixtures'
import { TraceSummaryBar } from './TraceSummaryBar'

const meta: Meta<typeof TraceSummaryBar> = {
    title: 'Scenes-App/AI observability/Trace view/Trace summary bar',
    component: TraceSummaryBar,
    args: {
        traceId: '3f9c2a71-5b8e-4d0f-a1c2-7e6d5b4a3c21',
        timestamp: '2026-09-01T10:15:00Z',
        person: { label: 'ana@example.com', href: '/person/ana' },
        totals: FIXTURE_STATS,
    },
}
export default meta

type Story = StoryObj<typeof TraceSummaryBar>

// The bar is an inline-size container, which contributes no intrinsic width, so an unsized story root collapses to zero.
const wide: Story = { decorators: [withWidth(960)] }

export const Default: Story = wide
export const Anonymous: Story = { ...wide, args: { person: null } }
export const ShortId: Story = { ...wide, args: { traceId: 'notes-run-42' } }
export const LongSlugId: Story = { ...wide, args: { traceId: 'support-chat-session-2026-09-01-weekly-billing-review' } }
export const Narrow: Story = { decorators: [withWidth(420)] }
