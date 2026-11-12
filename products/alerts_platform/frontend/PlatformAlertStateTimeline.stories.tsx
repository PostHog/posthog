import { Meta, StoryObj } from '@storybook/react'

import { PlatformAlertStateIndicator } from './PlatformAlertStateIndicator'
import { PlatformAlertStateTimeline } from './PlatformAlertStateTimeline'

const meta: Meta<typeof PlatformAlertStateTimeline> = {
    component: PlatformAlertStateTimeline,
    title: 'Products/Alerts platform/State timeline',
    parameters: { layout: 'padded', mockDate: '2026-11-11T12:00:00Z' },
}
export default meta

type Story = StoryObj<typeof PlatformAlertStateTimeline>

export const States: Story = {
    render: () => (
        <div className="space-y-4 w-[480px]">
            <div className="flex items-center gap-2">
                <PlatformAlertStateIndicator state="firing" />
                <PlatformAlertStateIndicator state="not_firing" />
                <PlatformAlertStateIndicator state="errored" lastErrorMessage="The check query timed out." />
                <PlatformAlertStateIndicator state="snoozed" snoozeUntil="2026-11-11T18:00:00Z" />
                <PlatformAlertStateIndicator state="broken" />
                <PlatformAlertStateIndicator state="not_firing" enabled={false} firstEnabledAt="2026-11-01T00:00:00Z" />
            </div>
            <PlatformAlertStateTimeline
                className="h-8 w-full"
                showAxis
                timeline={[
                    { start: '2026-11-10T12:00:00Z', end: '2026-11-11T02:00:00Z', state: 'not_firing', enabled: true },
                    { start: '2026-11-11T02:00:00Z', end: '2026-11-11T03:30:00Z', state: 'firing', enabled: true },
                    { start: '2026-11-11T03:30:00Z', end: '2026-11-11T06:00:00Z', state: 'snoozed', enabled: true },
                    { start: '2026-11-11T06:00:00Z', end: '2026-11-11T08:00:00Z', state: 'errored', enabled: true },
                    { start: '2026-11-11T08:00:00Z', end: '2026-11-11T10:00:00Z', state: 'not_firing', enabled: false },
                    { start: '2026-11-11T10:00:00Z', end: '2026-11-11T12:00:00Z', state: 'not_firing', enabled: true },
                ]}
            />
        </div>
    ),
}
