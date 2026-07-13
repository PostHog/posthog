import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import { Button } from '@posthog/quill'

import {
    ALL_TIME_PRESET,
    INSIGHT_DATE_PRESETS,
    type InsightDatePreset,
} from 'scenes/insights/filters/InsightDateFilter/insightDateFilterNextUtils'

import { DateExclusionsControl } from './DateExclusionsControl'
import { DateRangeFilter, type DateRangePreset } from './DateRangeFilter'

const PRESETS: DateRangePreset<InsightDatePreset>[] = [...INSIGHT_DATE_PRESETS, ALL_TIME_PRESET].map((preset) => ({
    id: preset.dateFrom,
    label: preset.name,
    value: preset,
    previewStart: (now: Date) => preset.rangeSetter(now, 1),
    previewEnd: preset.endSetter ? (now: Date) => preset.endSetter!(now, 1) : undefined,
}))

function DateRangeFilterDemo({ lemonSkin }: { lemonSkin: boolean }): JSX.Element {
    const [selectedPresetId, setSelectedPresetId] = useState<string | null>('-7d')
    const [custom, setCustom] = useState<{ start: Date; end: Date } | null>(null)
    const [excludedDays, setExcludedDays] = useState<number[]>([])
    const [excludeIncomplete, setExcludeIncomplete] = useState(false)

    const selected = PRESETS.find((preset) => preset.id === selectedPresetId)
    const label = custom
        ? `${custom.start.toLocaleDateString()} - ${custom.end.toLocaleDateString()}`
        : (selected?.label ?? 'Last 7 days')

    const skinAttrs = lemonSkin ? { 'data-lemon-skin': 'true' } : {}
    return (
        <div className="flex h-[600px] items-start p-4" data-quill {...skinAttrs}>
            <DateRangeFilter
                presets={PRESETS}
                selectedPresetId={custom ? null : selectedPresetId}
                onPresetSelect={(preset) => {
                    setSelectedPresetId(preset.id)
                    setCustom(null)
                }}
                onCustomApply={(start, end) => {
                    setCustom({ start, end })
                    setSelectedPresetId(null)
                }}
                customActive={!!custom}
                customStart={custom?.start}
                customEnd={custom?.end}
                footerExtra={
                    <DateExclusionsControl
                        excludedDays={excludedDays}
                        onExcludedDaysChange={setExcludedDays}
                        excludeIncomplete={excludeIncomplete}
                        onExcludeIncompleteChange={setExcludeIncomplete}
                    />
                }
                contentProps={skinAttrs as unknown as React.ComponentProps<typeof DateRangeFilter>['contentProps']}
                trigger={
                    <Button variant="outline" size="default" data-quill {...skinAttrs}>
                        <IconCalendar />
                        {label}
                    </Button>
                }
            />
        </div>
    )
}

const meta: Meta<typeof DateRangeFilterDemo> = {
    title: 'Components/Date Range Filter',
    parameters: {
        viewMode: 'story',
    },
}
export default meta
type Story = StoryObj<typeof DateRangeFilterDemo>

/** The insight date filter's shape with the lemon skin applied (lemon-skin.scss). */
export const LemonSkin: Story = {
    render: () => <DateRangeFilterDemo lemonSkin />,
}

/** The same filter with quill's native styling, for comparison. */
export const QuillNative: Story = {
    render: () => <DateRangeFilterDemo lemonSkin={false} />,
}
