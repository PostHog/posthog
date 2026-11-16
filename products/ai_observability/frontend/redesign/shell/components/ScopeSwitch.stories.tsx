import type { Meta, StoryObj } from '@storybook/react'

import { shellTab } from '../shellNavigation'
import { ScopeSwitch } from './ScopeSwitch'

const meta: Meta<typeof ScopeSwitch> = {
    title: 'Scenes-App/AI observability/Shell/Scope switch',
    component: ScopeSwitch,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { scopes: shellTab('activity')?.scopes ?? [], onScopeChange: () => {} },
}
export default meta

type Story = StoryObj<typeof ScopeSwitch>

export const SecondOptionActive: Story = { args: { activeScope: 'traces' } }

export const NarrowContainer: Story = {
    args: { activeScope: 'sessions' },
    decorators: [
        (StoryComponent) => (
            <div className="w-48">
                <StoryComponent />
            </div>
        ),
    ],
}
