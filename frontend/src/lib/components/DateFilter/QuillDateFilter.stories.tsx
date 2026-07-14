import type { Meta, StoryObj } from '@storybook/react'
import { type ReactNode, useState } from 'react'

import {
    Button as QuillButton,
    DateTimePicker,
    dateRangeSelectionLabel,
    Label as QuillLabel,
    Popover as QuillPopover,
    PopoverContent as QuillPopoverContent,
    PopoverTrigger as QuillPopoverTrigger,
    Switch as QuillSwitch,
    type DataAttributeProps,
    type DateRangeSelection,
} from '@posthog/quill'

import {
    DateFilterExclusionsControl,
    dateFilterExclusionParts,
    type DateFilterExclusions,
} from './DateFilterExclusionsControl'

// The quill DateTimePicker in presets-panel mode, twice: under the lemon skin (lemon-skin.scss
// rebinds quill under `data-lemon-skin` — same code, lemon look) and quill-native.

const meta: Meta = {
    title: 'Components/Quill Date Filter',
    parameters: {
        mockDate: '2026-07-13',
    },
}
export default meta
type Story = StoryObj

function ConceptColumn({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-secondary">{title}</span>
            {children}
        </div>
    )
}

function shortExclusionsLabel(parts: string[]): string {
    return parts.length > 1 ? `excl. ${parts[0]} +${parts.length - 1}` : `excl. ${parts[0]}`
}

function DateFilterConcept({ lemonSkin }: { lemonSkin?: boolean }): JSX.Element {
    const [selection, setSelection] = useState<DateRangeSelection>({ kind: 'rolling', count: 30, unit: 'days' })
    const [exclusions, setExclusions] = useState<DateFilterExclusions>({ days: [], incomplete: false })
    const [exactTime, setExactTime] = useState(false)
    const [open, setOpen] = useState(false)
    const exclusionParts = dateFilterExclusionParts(exclusions)
    const skinProps = lemonSkin ? { 'data-lemon-skin': true, 'data-quill': true } : {}
    const portalProps = lemonSkin ? ({ 'data-lemon-skin': 'true' } as DataAttributeProps) : undefined
    return (
        <QuillPopover open={open} onOpenChange={setOpen}>
            <QuillPopoverTrigger render={<QuillButton variant="outline" {...skinProps} />}>
                {dateRangeSelectionLabel(selection)}
                {exclusionParts.length > 0 && (
                    <span className="text-muted-foreground font-normal">· {shortExclusionsLabel(exclusionParts)}</span>
                )}
            </QuillPopoverTrigger>
            <QuillPopoverContent
                align="start"
                collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                {...(lemonSkin ? { 'data-lemon-skin': true } : {})}
            >
                <DateTimePicker
                    selection={selection}
                    onSelectionChange={(next) => {
                        setSelection(next)
                        if (next.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    onApply={({ start, end, includesTime }) => {
                        setSelection({ kind: 'custom', start, end, includesTime })
                        setOpen(false)
                    }}
                    showHeader={false}
                    showTime={false}
                    showTimeToggle
                    portalProps={portalProps}
                    presetsFooter={
                        <>
                            <div className="flex h-8 items-center justify-between gap-2 px-2">
                                <QuillLabel htmlFor="date-filter-exact-time">Exact time range</QuillLabel>
                                <QuillSwitch
                                    id="date-filter-exact-time"
                                    size="sm"
                                    checked={exactTime}
                                    onCheckedChange={setExactTime}
                                />
                            </div>
                            <DateFilterExclusionsControl
                                exclusions={exclusions}
                                onChange={setExclusions}
                                showDays
                                showIncomplete
                                panelProps={portalProps}
                            />
                        </>
                    }
                />
            </QuillPopoverContent>
        </QuillPopover>
    )
}

export const DateFilter: Story = {
    render: () => (
        <div className="flex flex-wrap items-start gap-8 pb-[40rem]">
            <ConceptColumn title="Date filter · lemon skin">
                <DateFilterConcept lemonSkin />
            </ConceptColumn>
            <ConceptColumn title="Date filter · quill">
                <DateFilterConcept />
            </ConceptColumn>
        </div>
    ),
}
