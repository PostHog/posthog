import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import type { ReportScheduleCadence, ReportScheduleWeekday } from '../evaluationReportLogic'
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
    const [cadence, setCadence] = useState<ReportScheduleCadence>('weekly')
    const [weekdays, setWeekdays] = useState<ReportScheduleWeekday[]>(['MO', 'FR'])
    const toggleWeekday = (weekday: ReportScheduleWeekday): void => {
        setWeekdays((current) =>
            current.includes(weekday)
                ? current.filter((currentWeekday) => currentWeekday !== weekday)
                : [...current, weekday]
        )
    }
    return (
        <div className="w-100">
            <ScheduleConfig
                cadence={cadence}
                weekdays={weekdays}
                onCadenceChange={setCadence}
                onWeekdayToggle={toggleWeekday}
            />
        </div>
    )
}

export const LemonUI: Story = { render: () => <Template /> }

export const Quill: Story = {
    render: () => <Template />,
    parameters: { mockDate: '2026-01-15', featureFlags: [FEATURE_FLAGS.QUILL_DATE_PICKER] },
}
