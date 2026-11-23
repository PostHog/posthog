import type { Meta, StoryObj } from '@storybook/react'

import { CHECKLIST_PENDING, CHECKLIST_WARNING } from '../homeFixtures'
import { InstrumentationRow } from './InstrumentationRow'

const meta: Meta<typeof InstrumentationRow> = {
    title: 'Scenes-App/AI observability/Home/Instrumentation row',
    component: InstrumentationRow,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        checklist: CHECKLIST_PENDING,
        loading: false,
        pendingCheckKey: null,
        refreshing: false,
        refreshFailed: false,
        onDismiss: () => {},
        onRestore: () => {},
        onRefresh: () => {},
    },
}
export default meta

type Story = StoryObj<typeof InstrumentationRow>

export const NothingWarnsCollapsed: Story = {}

export const WarningOpenWithPrompt: Story = { args: { checklist: CHECKLIST_WARNING } }

export const Loading: Story = { args: { checklist: null, loading: true } }

export const RefreshFailed: Story = { args: { checklist: CHECKLIST_WARNING, refreshFailed: true } }
