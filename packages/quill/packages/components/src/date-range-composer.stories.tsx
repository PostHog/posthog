import type { Meta, StoryObj } from '@storybook/react'
import * as React from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill-primitives'

import {
    composerExclusionsSummary,
    composerSelectionLabel,
    DateRangeComposer,
    type DateRangeComposerExclusions,
    type DateRangeComposerSelection,
} from './date-range-composer'
import { RelativeRangeInput, type RelativeRangeValue } from './relative-range-input'

const meta = {
    title: 'Components/DateRangeComposer',
    component: DateRangeComposer,
    tags: ['autodocs'],
} satisfies Meta<typeof DateRangeComposer>

export default meta
type Story = StoryObj<typeof meta>

const baseArgs = {
    selection: { kind: 'rolling', count: 7, unit: 'days' } as DateRangeComposerSelection,
    onSelect: () => undefined,
    exclusions: { days: [], incomplete: false },
    onExclusionsChange: () => undefined,
}

export const Composer: Story = {
    args: baseArgs,
    render: () => {
        const [selection, setSelection] = React.useState<DateRangeComposerSelection>({
            kind: 'rolling',
            count: 7,
            unit: 'days',
        })
        const [exclusions, setExclusions] = React.useState<DateRangeComposerExclusions>({
            days: [],
            incomplete: false,
        })
        return (
            <DateRangeComposer
                selection={selection}
                onSelect={setSelection}
                exclusions={exclusions}
                onExclusionsChange={setExclusions}
            />
        )
    },
}

export const ComposerInPopover: Story = {
    args: baseArgs,
    render: () => {
        const [selection, setSelection] = React.useState<DateRangeComposerSelection>({
            kind: 'rolling',
            count: 7,
            unit: 'days',
        })
        const [exclusions, setExclusions] = React.useState<DateRangeComposerExclusions>({
            days: [],
            incomplete: false,
        })
        const [open, setOpen] = React.useState(false)
        const summary = composerExclusionsSummary(exclusions)
        return (
            <div className="h-140">
                <Popover open={open} onOpenChange={setOpen}>
                    <PopoverTrigger render={<Button variant="outline" />}>
                        {composerSelectionLabel(selection)}
                        {summary && <span className="size-1.5 rounded-full bg-primary" aria-label={summary} />}
                    </PopoverTrigger>
                    <PopoverContent
                        align="start"
                        collisionAvoidance={{ side: 'flip', align: 'none', fallbackAxisSide: 'none' }}
                        className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                    >
                        <DateRangeComposer
                            selection={selection}
                            onSelect={(next) => {
                                setSelection(next)
                                if (next.kind !== 'rolling') {
                                    setOpen(false)
                                }
                            }}
                            exclusions={exclusions}
                            onExclusionsChange={setExclusions}
                        />
                    </PopoverContent>
                </Popover>
            </div>
        )
    },
}

export const StandaloneInput: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<RelativeRangeValue>({
            count: 30,
            unit: 'days',
        })
        return (
            <div className="flex items-center gap-2">
                <Text size="sm" weight="semibold" render={<span />}>
                    Last
                </Text>
                <RelativeRangeInput value={value} onChange={setValue} />
            </div>
        )
    },
}
