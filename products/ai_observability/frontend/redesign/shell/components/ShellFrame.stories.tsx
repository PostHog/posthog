import type { Meta, StoryObj } from '@storybook/react'

import { ShellFrame } from './ShellFrame'

const meta: Meta<typeof ShellFrame> = {
    title: 'Scenes-App/AI observability/Shell/Shell frame',
    component: ShellFrame,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        linkParams: {},
        todayRailNav: false,
        onScopeChange: () => {},
        children: <div className="border rounded p-4 text-secondary">Tab content</div>,
    },
}
export default meta

type Story = StoryObj<typeof ShellFrame>

export const Home: Story = { args: { location: { tab: 'home', scope: null } } }

export const ActivityOnTraces: Story = { args: { location: { tab: 'activity', scope: 'traces' } } }

export const PathWithoutATab: Story = { args: { location: { tab: null, scope: null } } }

export const NarrowActivity: Story = {
    args: { location: { tab: 'activity', scope: 'sessions' } },
    decorators: [
        (StoryComponent) => (
            <div className="w-96">
                <StoryComponent />
            </div>
        ),
    ],
}
