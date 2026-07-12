import type { Meta, StoryObj } from '@storybook/react'
import { subDays, subMonths } from 'date-fns'

import { Label, Switch } from '@posthog/quill-primitives'

import { DateRangeFilter, type DateRangeFilterPreset } from './date-range-filter'

const ANALYTICS_PRESETS: DateRangeFilterPreset<string>[] = [
    { id: 'today', label: 'Today', value: 'dStart', previewStart: (now) => now },
    { id: '7d', label: 'Last 7 days', value: '-7d', previewStart: (now) => subDays(now, 7) },
    { id: '30d', label: 'Last 30 days', value: '-30d', previewStart: (now) => subDays(now, 30) },
    { id: '90d', label: 'Last 90 days', value: '-90d', previewStart: (now) => subDays(now, 90) },
    { id: 'mStart', label: 'This month', value: 'mStart', previewStart: (now) => subMonths(now, 1) },
    { id: 'all', label: 'All time', value: 'all', previewStart: (now) => subMonths(now, 60) },
]

const meta: Meta<typeof DateRangeFilter> = {
    title: 'Blocks/DateRangeFilter',
    component: DateRangeFilter,
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof DateRangeFilter>

export const PresetList: Story = {
    render: () => (
        <div className="h-96">
            <DateRangeFilter
                label="Last 7 days"
                presets={ANALYTICS_PRESETS}
                selectedPresetId="7d"
                onPresetSelect={() => {}}
                onCustomApply={() => {}}
                defaultOpen
            />
        </div>
    ),
}

export const WithListFooter: Story = {
    render: () => (
        <div className="h-96">
            <DateRangeFilter
                label="Last 7 days"
                presets={ANALYTICS_PRESETS}
                selectedPresetId="7d"
                onPresetSelect={() => {}}
                onCustomApply={() => {}}
                defaultOpen
                listFooter={
                    <div className="flex items-center gap-2 px-2 py-2">
                        <Label htmlFor="story-exclude-incomplete">Exclude incomplete period</Label>
                        <Switch id="story-exclude-incomplete" size="sm" />
                    </div>
                }
            />
        </div>
    ),
}

export const CustomRangeActive: Story = {
    render: () => (
        <div className="h-120">
            <DateRangeFilter
                label="Jan 10 – Jan 20"
                presets={ANALYTICS_PRESETS}
                customActive
                customStart={new Date(2023, 0, 10)}
                customEnd={new Date(2023, 0, 20)}
                onPresetSelect={() => {}}
                onCustomApply={() => {}}
                defaultOpen
            />
        </div>
    ),
}
