import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { PostHogTeamCohortBanner } from './PostHogTeamCohortBanner'

function OptedOutBanner({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const { setExcludedFromPostHogTeamCohort } = useActions(superpowersLogic)
    useOnMountEffect(() => setExcludedFromPostHogTeamCohort(true))

    return (
        <div className={isCollapsed ? 'w-fit' : 'w-[var(--project-navbar-width)]'}>
            <PostHogTeamCohortBanner isCollapsed={isCollapsed} />
        </div>
    )
}

const meta: Meta<typeof OptedOutBanner> = {
    title: 'Layout/Navigation sidebar/PostHog Team cohort banner',
    component: OptedOutBanner,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof OptedOutBanner>

export const Expanded: Story = { args: { isCollapsed: false } }

export const Collapsed: Story = { args: { isCollapsed: true } }
