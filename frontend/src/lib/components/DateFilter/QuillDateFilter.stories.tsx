import type { Meta, StoryObj } from '@storybook/react'
import { type ReactNode, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Button as QuillButton,
    Label as QuillLabel,
    Popover as QuillPopover,
    PopoverContent as QuillPopoverContent,
    PopoverTrigger as QuillPopoverTrigger,
    Switch as QuillSwitch,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import {
    DateFilterExclusionsControl,
    dateFilterExclusionParts,
    type DateFilterExclusions,
} from './DateFilterExclusionsControl'
import { dateRangeSelectionLabel, type DataAttributeProps, type DateRangeSelection } from './DateRangePresetsPanel'
import { QuillDateFilter } from './QuillDateFilter'

// The experimental chip-based date filter, twice: under the lemon skin (lemon-skin.scss rebinds
// quill under `data-lemon-skin` — same code, lemon look) and quill-native.

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
                <QuillDateFilter
                    selection={selection}
                    onSelectionChange={(next) => {
                        setSelection(next)
                        if (next.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    onApplyCustom={(next) => {
                        setSelection(next)
                        setOpen(false)
                    }}
                    portalProps={portalProps}
                    presetsFooter={
                        <>
                            <div className="flex h-8 items-center justify-between gap-2 px-2">
                                <QuillLabel htmlFor="date-filter-exact-time" className="flex items-center gap-1">
                                    Exact time range
                                    <Tooltip>
                                        <TooltipTrigger render={<span className="inline-flex" />}>
                                            <IconInfo className="h-4 w-4 text-muted-foreground" />
                                        </TooltipTrigger>
                                        <TooltipContent className="max-w-64 flex-col items-start whitespace-normal">
                                            <span>
                                                When enabled: uses the current time for period boundaries instead of
                                                full days.
                                            </span>
                                            <span>
                                                When disabled: dates are rounded to full day periods (start and end of
                                                day).
                                            </span>
                                        </TooltipContent>
                                    </Tooltip>
                                </QuillLabel>
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
