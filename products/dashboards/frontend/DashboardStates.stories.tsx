import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { Link } from 'lib/lemon-ui/Link'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { EmptyDashboardComponent } from 'scenes/dashboard/EmptyDashboardComponent'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { urls } from 'scenes/urls'

import { DashboardLoadingState } from './components/DashboardLoadingState/DashboardLoadingState'

const DASHBOARD_STATES = [
    'Loading',
    'Not found',
    'Access denied',
    'Server error',
    'Empty, editable',
    'Empty, read-only',
] as const

type DashboardState = (typeof DASHBOARD_STATES)[number]

function DashboardStateStory({ state }: { state: DashboardState }): JSX.Element {
    switch (state) {
        case 'Loading':
            return (
                <BindLogic logic={dashboardLogic} props={{ id: 1 }}>
                    <div className="flex flex-col gap-4 p-4">
                        <DashboardHeader loading />
                        <DashboardLoadingState />
                    </div>
                </BindLogic>
            )
        case 'Not found':
            return (
                <NotFound
                    object="dashboard"
                    caption={
                        <>
                            It may have been deleted, or the link is out of date.{' '}
                            <Link to={urls.dashboards()}>Go to your dashboards</Link>.
                        </>
                    }
                />
            )
        case 'Access denied':
            return <AccessDenied object="dashboard" />
        case 'Server error':
            return <InsightErrorState title="There was an error loading this dashboard" supportOnly />
        case 'Empty, editable':
        case 'Empty, read-only':
            return (
                <BindLogic logic={dashboardLogic} props={{ id: 1 }}>
                    <EmptyDashboardComponent loading={false} canEdit={state === 'Empty, editable'} />
                </BindLogic>
            )
    }
}

const meta: Meta<typeof DashboardStateStory> = {
    component: DashboardStateStory,
    title: 'Products/Dashboards',
    args: {
        state: 'Loading',
    },
    argTypes: {
        state: {
            control: 'select',
            options: DASHBOARD_STATES,
        },
    },
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForLoadersToDisappear: false },
        viewMode: 'story',
    },
}

export default meta

type Story = StoryObj<typeof DashboardStateStory>

export const DashboardStates: Story = {}
