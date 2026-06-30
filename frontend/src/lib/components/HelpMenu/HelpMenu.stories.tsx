import type { Meta, StoryObj } from '@storybook/react'
import { screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'

import { HelpMenu } from './HelpMenu'

// The health-issues summary is the only request the menu makes that the default Storybook
// mocks (billing, preflight, users/@me, status page) don't already cover. Mocking it drives
// the trigger/Health badge state deterministically.
const HEALTHY_SUMMARY = { total: 0, by_severity: {}, by_kind: {} }
const UNHEALTHY_SUMMARY = {
    total: 3,
    by_severity: { critical: 1, warning: 2 },
    by_kind: { ingestion_warning: 2, query_error: 1 },
}

// The menu popup portals to <body>; the trigger lives in the story canvas. We scope each
// snapshot to whichever element the story is about, rather than the (mostly empty) page.
const POPUP = '.primitive-menu-content'
const TRIGGER = '[data-attr="more-menu-button"]'

const meta: Meta<typeof HelpMenu> = {
    title: 'Components/Help Menu',
    component: HelpMenu,
    parameters: {
        // Not `fullscreen` — the runner rejects snapshotTargetSelector for fullscreen stories.
        layout: 'centered',
        // Tall viewport so the open menu renders its full height without the popup's internal
        // ScrollableShadows clipping items (it's capped at the available height).
        testOptions: { viewport: { width: 600, height: 960 } },
    },
}
export default meta

type Story = StoryObj<typeof HelpMenu>

async function openMenu(): Promise<void> {
    await userEvent.click(document.querySelector(TRIGGER) as HTMLElement)

    // Menu items render into a portal at the document root, so query the screen, not the canvas.
    await screen.findByText('Ask PostHog AI')
}

export const Open: Story = {
    decorators: [mswDecorator({ get: { '/api/environments/:team_id/health_issues/summary/': HEALTHY_SUMMARY } })],
    play: openMenu,
    parameters: { testOptions: { snapshotTargetSelector: POPUP, waitForSelector: POPUP } },
}

export const OpenWithHealthIssues: Story = {
    decorators: [mswDecorator({ get: { '/api/environments/:team_id/health_issues/summary/': UNHEALTHY_SUMMARY } })],
    play: openMenu,
    parameters: { testOptions: { snapshotTargetSelector: POPUP, waitForSelector: POPUP } },
}
