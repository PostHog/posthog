import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import {
    ForecastConditionType,
    ForecastConfig,
    ForecastEngineType,
    ForecastTargetDirection,
} from '~/queries/schema/schema-general'

import { ForecastSelector } from './ForecastSelector'

function SelectorStory({ initialValue }: { initialValue: ForecastConfig }): JSX.Element {
    const [value, setValue] = useState(initialValue)
    return <ForecastSelector value={value} onChange={setValue} insightInterval="day" targetDateError={null} />
}

const meta: Meta<typeof ForecastSelector> = {
    title: 'Products/Alerts/Forecast selector',
    component: ForecastSelector,
    parameters: { layout: 'fullscreen', mockDate: '2026-09-07' },
    decorators: [
        (Story): JSX.Element => (
            <div className="min-h-screen bg-bg-primary p-4">
                <div className="max-w-xl border rounded bg-surface-primary p-4">
                    <Story />
                </div>
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof meta>

export const UpcomingThresholdBreach: Story = {
    render: () => (
        <SelectorStory
            initialValue={{
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.FUTURE_BREACH,
                horizon: 14,
            }}
        />
    ),
}

export const TargetByDate: Story = {
    render: () => (
        <SelectorStory
            initialValue={{
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target: 250_000,
                target_direction: ForecastTargetDirection.AT_LEAST,
                target_date: '2026-12-01',
            }}
        />
    ),
}

export const TargetByDateNarrow: Story = {
    ...TargetByDate,
    decorators: [
        (Story): JSX.Element => (
            <div className="w-[360px] border rounded bg-surface-primary p-3">
                <Story />
            </div>
        ),
    ],
}
