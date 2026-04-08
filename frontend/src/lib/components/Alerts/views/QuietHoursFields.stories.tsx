import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import type { ScheduleRestriction } from '../types'
import type { QuietHoursFieldsProps } from './QuietHoursFields'
import { QuietHoursFields } from './QuietHoursFields'

type QuietHoursStoryArgs = Omit<QuietHoursFieldsProps, 'scheduleRestriction' | 'onChange'> & {
    /** Quiet hours checkbox + initial state; include in host `key` so Storybook can reset. */
    quietHoursEnabled: boolean
    /** Seeds the first row until controls change (see `key` on the host). */
    windowStart: string
    windowEnd: string
}

function QuietHoursStoryHost({
    quietHoursEnabled,
    windowStart,
    windowEnd,
    teamTimezone,
    calculationInterval,
}: QuietHoursStoryArgs): JSX.Element {
    const [scheduleRestriction, setScheduleRestriction] = useState<ScheduleRestriction | null>(() =>
        quietHoursEnabled ? { blocked_windows: [{ start: windowStart, end: windowEnd }] } : null
    )

    return (
        <QuietHoursFields
            scheduleRestriction={scheduleRestriction}
            onChange={setScheduleRestriction}
            teamTimezone={teamTimezone}
            calculationInterval={calculationInterval}
        />
    )
}

const meta: Meta<QuietHoursStoryArgs> = {
    title: 'Components/Alerts/Quiet hours fields',
    args: {
        quietHoursEnabled: true,
        windowStart: '22:00',
        windowEnd: '07:00',
        teamTimezone: 'America/New_York',
        calculationInterval: AlertCalculationInterval.HOURLY,
    },
    argTypes: {
        quietHoursEnabled: { control: 'boolean' },
        windowStart: { control: 'text' },
        windowEnd: { control: 'text' },
        calculationInterval: {
            control: 'select',
            options: Object.values(AlertCalculationInterval),
        },
    },
    render: (args) => (
        <div className="max-w-[600px]">
            <QuietHoursStoryHost
                key={`${args.quietHoursEnabled}-${args.windowStart}-${args.windowEnd}-${args.teamTimezone}-${args.calculationInterval}`}
                {...args}
            />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}
