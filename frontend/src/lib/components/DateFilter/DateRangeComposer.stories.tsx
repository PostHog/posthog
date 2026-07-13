import type { Meta, StoryObj } from '@storybook/react'
import { type ReactNode, useState } from 'react'

import {
    Button as QuillButton,
    composerExclusionsSummary,
    composerSelectionLabel,
    CUSTOM_RANGE,
    DateRangeComposer,
    DateTimePicker,
    Popover as QuillPopover,
    PopoverContent as QuillPopoverContent,
    PopoverTrigger as QuillPopoverTrigger,
    quickRanges,
    type DateRangeComposerExclusions,
    type DateRangeComposerSelection,
    type DateTimeValue,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

// The date filter redesign concepts, one quill implementation each, shown twice: raw quill
// and wrapped in the lemon skin (lemon-skin.scss rebinds quill tokens under
// `data-lemon-skin` — same code, lemon look; see InsightDateFilterNext for the production
// pattern). No hand-rolled Lemon twins.

const meta: Meta = {
    title: 'Components/Date Range Composer',
    parameters: {
        mockDate: '2026-07-13',
    },
    tags: ['autodocs'],
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

function ComposerConcept({ lemonSkin }: { lemonSkin?: boolean }): JSX.Element {
    const [selection, setSelection] = useState<DateRangeComposerSelection>({
        kind: 'rolling',
        count: 7,
        unit: 'days',
    })
    const [exclusions, setExclusions] = useState<DateRangeComposerExclusions>({ days: [], incomplete: false })
    const [open, setOpen] = useState(false)
    const summary = composerExclusionsSummary(exclusions)
    const skinProps = lemonSkin ? { 'data-lemon-skin': true, 'data-quill': true } : {}
    return (
        <QuillPopover open={open} onOpenChange={setOpen}>
            <QuillPopoverTrigger render={<QuillButton variant="outline" {...skinProps} />}>
                {composerSelectionLabel(selection)}
                {summary && <span className="size-1.5 rounded-full bg-primary" aria-label={summary} />}
            </QuillPopoverTrigger>
            <QuillPopoverContent
                align="start"
                collisionAvoidance={{ side: 'flip', align: 'none', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                {...(lemonSkin ? { 'data-lemon-skin': true } : {})}
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
            </QuillPopoverContent>
        </QuillPopover>
    )
}

function PresetsFirstConcept({ lemonSkin }: { lemonSkin?: boolean }): JSX.Element {
    const [value, setValue] = useState<DateTimeValue>({
        start: dayjs().subtract(7, 'day').toDate(),
        end: dayjs().toDate(),
        range: quickRanges.find((r) => r.name === 'Last 7 days')!,
    })
    const [open, setOpen] = useState(false)
    const label =
        value.range.id !== CUSTOM_RANGE.id
            ? value.range.name
            : `${dayjs(value.start).format('MMM D')} – ${dayjs(value.end).format('MMM D')}`
    const skinProps = lemonSkin ? { 'data-lemon-skin': true, 'data-quill': true } : {}
    return (
        <QuillPopover open={open} onOpenChange={setOpen}>
            <QuillPopoverTrigger render={<QuillButton variant="outline" {...skinProps} />}>{label}</QuillPopoverTrigger>
            <QuillPopoverContent
                align="start"
                collisionAvoidance={{ side: 'flip', align: 'none', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                {...(lemonSkin ? { 'data-lemon-skin': true } : {})}
            >
                <DateTimePicker
                    presetsFirst
                    showTime={false}
                    value={value}
                    onApply={(next) => {
                        setValue(next)
                        setOpen(false)
                    }}
                />
            </QuillPopoverContent>
        </QuillPopover>
    )
}

export const AllConcepts: Story = {
    render: () => (
        <div className="flex flex-wrap items-start gap-8 pb-[40rem]">
            <ConceptColumn title="Composer · quill">
                <ComposerConcept />
            </ConceptColumn>
            <ConceptColumn title="Composer · lemon skin">
                <ComposerConcept lemonSkin />
            </ConceptColumn>
            <ConceptColumn title="Presets-first · quill">
                <PresetsFirstConcept />
            </ConceptColumn>
            <ConceptColumn title="Presets-first · lemon skin">
                <PresetsFirstConcept lemonSkin />
            </ConceptColumn>
        </div>
    ),
}
