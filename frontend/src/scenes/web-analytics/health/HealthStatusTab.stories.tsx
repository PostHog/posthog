import { Meta, StoryFn } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { HealthStatusTab } from './HealthStatusTab'

const HEALTH_ISSUES = {
    results: [
        { kind: 'no_live_events', severity: 'critical' },
        { kind: 'web_vitals', severity: 'warning' },
    ],
}

const meta: Meta<typeof HealthStatusTab> = {
    title: 'Scenes-App/Web Analytics/Installation health',
    component: HealthStatusTab,
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/health_issues/': HEALTH_ISSUES },
        }),
    ],
    parameters: { layout: 'padded', testOptions: { waitForLoadersToDisappear: true } },
}
export default meta

export const InstallationHealth: StoryFn = () => <HealthStatusTab />

export const InstallationHealthNarrow: StoryFn = () => (
    <div className="w-[520px]">
        <HealthStatusTab />
    </div>
)
