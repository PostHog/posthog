import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'

import { HelpMenu } from './HelpMenu'
import { helpMenuLogic } from './helpMenuLogic'

// The health-issues summary is the only request the menu makes that the default Storybook
// mocks (billing, preflight, users/@me, status page) don't already cover. Mocking it drives
// the trigger/Health badge state deterministically.
const HEALTHY_SUMMARY = { total: 0, by_severity: {}, by_kind: {} }
const UNHEALTHY_SUMMARY = {
    total: 3,
    by_severity: { critical: 1, warning: 2 },
    by_kind: { ingestion_warning: 2, query_error: 1 },
}

const meta: Meta<typeof HelpMenu> = {
    title: 'Components/Help Menu',
    component: HelpMenu,
    render: () => {
        const { setHelpMenuOpen } = useActions(helpMenuLogic)
        useOnMountEffect(() => setHelpMenuOpen(true))

        return (
            <div className="flex h-[1400px] w-[600px]">
                <HelpMenu />
            </div>
        )
    },
    parameters: {
        // Not `fullscreen` — the runner rejects snapshotTargetSelector for fullscreen stories.
        layout: 'centered',
        // Tall viewport so the open menu renders its full height without the popup's internal
        // ScrollableShadows clipping items (it's capped at the available height).
        testOptions: { viewport: { width: 600, height: 1400 } },
    },
}
export default meta

type Story = StoryObj<typeof HelpMenu>

export const Open: Story = {
    decorators: [mswDecorator({ get: { '/api/environments/:team_id/health_issues/summary/': HEALTHY_SUMMARY } })],
}

export const OpenWithHealthIssues: Story = {
    decorators: [mswDecorator({ get: { '/api/environments/:team_id/health_issues/summary/': UNHEALTHY_SUMMARY } })],
}
