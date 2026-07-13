import type { Meta, StoryObj } from '@storybook/react'
import { type ReactNode, useState } from 'react'

import {
    Button as QuillButton,
    composerExclusionsSummary,
    composerSelectionLabel,
    DateRangeComposer,
    Popover as QuillPopover,
    PopoverContent as QuillPopoverContent,
    PopoverTrigger as QuillPopoverTrigger,
    type DateRangeComposerExclusions,
    type DateRangeComposerProps,
    type DateRangeComposerSelection,
} from '@posthog/quill'

// The quill DateRangeComposer, twice: under the lemon skin (lemon-skin.scss rebinds
// quill under `data-lemon-skin` — same code, lemon look) and quill-native.

const meta: Meta = {
    title: 'Components/Date Range Composer',
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

// The trigger caps the exclusion list at one item with a +N overflow.
function shortExclusionsLabel(summary: string): string {
    const parts = summary.replace('Excluding ', '').split(', ')
    return parts.length > 1 ? `excl. ${parts[0]} +${parts.length - 1}` : `excl. ${parts[0]}`
}

function ComposerConcept({ lemonSkin }: { lemonSkin?: boolean }): JSX.Element {
    const [selection, setSelection] = useState<DateRangeComposerSelection>({
        kind: 'rolling',
        count: 30,
        unit: 'days',
    })
    const [exclusions, setExclusions] = useState<DateRangeComposerExclusions>({ days: [], incomplete: false })
    const [exactTime, setExactTime] = useState(false)
    const [open, setOpen] = useState(false)
    const summary = composerExclusionsSummary(exclusions)
    const skinProps = lemonSkin ? { 'data-lemon-skin': true, 'data-quill': true } : {}
    const portalProps = lemonSkin
        ? ({ 'data-lemon-skin': 'true' } as unknown as DateRangeComposerProps['portalProps'])
        : undefined
    return (
        <QuillPopover open={open} onOpenChange={setOpen}>
            <QuillPopoverTrigger render={<QuillButton variant="outline" {...skinProps} />}>
                {composerSelectionLabel(selection)}
                {summary && (
                    <span className="text-muted-foreground font-normal">· {shortExclusionsLabel(summary)}</span>
                )}
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
                    exactTime={exactTime}
                    onExactTimeChange={setExactTime}
                    portalProps={portalProps}
                />
            </QuillPopoverContent>
        </QuillPopover>
    )
}

export const Composer: Story = {
    render: () => (
        <div className="flex flex-wrap items-start gap-8 pb-[40rem]">
            <ConceptColumn title="Composer · lemon skin">
                <ComposerConcept lemonSkin />
            </ConceptColumn>
            <ConceptColumn title="Composer · quill">
                <ComposerConcept />
            </ConceptColumn>
        </div>
    ),
}
