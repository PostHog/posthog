import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { ScheduleConfig } from './EvaluationReportConfig'

type Story = StoryObj<typeof ScheduleConfig>
const meta: Meta<typeof ScheduleConfig> = {
    title: 'Scenes-App/LLM observability/EvaluationReportConfig',
    component: ScheduleConfig,
    parameters: {
        mockDate: '2026-01-15',
    },
    tags: ['autodocs'],
}
export default meta

function Template(): JSX.Element {
    const [rrule, setRrule] = useState('FREQ=DAILY')
    const [startsAt, setStartsAt] = useState<string | null>('2026-01-15T09:30:00.000Z')
    const [timezoneName, setTimezoneName] = useState('UTC')
    return (
        <div className="w-100">
            <ScheduleConfig
                rrule={rrule}
                startsAt={startsAt}
                timezoneName={timezoneName}
                onRruleChange={setRrule}
                onStartsAtChange={setStartsAt}
                onTimezoneChange={setTimezoneName}
            />
        </div>
    )
}

export const LemonUI: Story = { render: () => <Template /> }

export const Quill: Story = {
    render: () => <Template />,
    parameters: { mockDate: '2026-01-15', featureFlags: [FEATURE_FLAGS.QUILL_DATE_PICKER] },
}
