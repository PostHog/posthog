import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { PostHogTeamCohortBanner } from './PostHogTeamCohortBanner'

const EXCLUDED_STORAGE_KEY = 'lib.components.Superpowers.superpowersLogic.excludedFromPostHogTeamCohort'

// Seeds the persisted opt-out instead of dispatching the toggle, whose listener writes person properties.
// The cleanup removes the seed, so later stories start with the default.
function withOptedOutOfCohort(Story: () => JSX.Element): JSX.Element {
    localStorage.setItem(EXCLUDED_STORAGE_KEY, JSON.stringify(true))
    useEffect(() => () => localStorage.removeItem(EXCLUDED_STORAGE_KEY), [])
    return <Story />
}

function OptedOutBanner({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    return (
        <div className={isCollapsed ? 'w-fit' : 'w-[var(--project-navbar-width)]'}>
            <PostHogTeamCohortBanner isCollapsed={isCollapsed} />
        </div>
    )
}

const meta: Meta<typeof OptedOutBanner> = {
    title: 'Layout/Navigation sidebar/PostHog Team cohort banner',
    component: OptedOutBanner,
    decorators: [withOptedOutOfCohort],
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof OptedOutBanner>

export const Expanded: Story = { args: { isCollapsed: false } }

export const Collapsed: Story = { args: { isCollapsed: true } }
