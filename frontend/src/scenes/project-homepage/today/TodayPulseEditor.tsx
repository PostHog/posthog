import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconPin, IconPinFilled, IconSearch } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Text,
} from '@posthog/quill'

import { PULSE_TILES, type PinnedPulseMetric, todayHighlightsLogic } from './todayHighlightsLogic'

function PulsePinRow({
    metric,
    pinned,
    disabledReason,
    onToggle,
}: {
    metric: PinnedPulseMetric
    pinned: boolean
    disabledReason?: string
    onToggle: () => void
}): JSX.Element {
    return (
        <li>
            <Button
                size="row"
                left
                aria-pressed={pinned}
                disabledReason={disabledReason}
                onClick={onToggle}
                className="group/pin w-full aria-pressed:bg-transparent aria-pressed:hover:bg-fill-hover"
                data-attr="today-pulse-pin"
            >
                <span className="min-w-0 flex-1 truncate text-left">{metric.name}</span>
                {pinned ? (
                    <IconPinFilled className="shrink-0" aria-hidden />
                ) : (
                    <IconPin
                        className="shrink-0 text-muted-foreground opacity-60 group-hover/pin:opacity-100 group-focus-visible/pin:opacity-100"
                        aria-hidden
                    />
                )}
            </Button>
        </li>
    )
}

export function TodayPulseEditor(): JSX.Element {
    const { pinnedPulseMetrics, pulseTiles, pulseInsightResults, pulseInsightResultsLoading } =
        useValues(todayHighlightsLogic)
    const { setPinnedPulseKeys, loadPulseInsightResults, pulseEditorOpened } = useActions(todayHighlightsLogic)
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const [shownOnOpen, setShownOnOpen] = useState<PinnedPulseMetric[]>([])

    const isPinned = (key: string): boolean => pinnedPulseMetrics.some((pinned) => pinned.key === key)
    const full = pinnedPulseMetrics.length >= PULSE_TILES
    const searching = search.trim().length > 0
    const rows = searching ? pulseInsightResults : shownOnOpen

    const toggle = (metric: PinnedPulseMetric): void => {
        setPinnedPulseKeys(
            isPinned(metric.key)
                ? pinnedPulseMetrics.filter((pinned) => pinned.key !== metric.key)
                : [...pinnedPulseMetrics, { key: metric.key, name: metric.name }]
        )
    }

    return (
        <Popover
            open={open}
            onOpenChange={(next) => {
                setOpen(next)
                if (next) {
                    pulseEditorOpened()
                    setShownOnOpen(pulseTiles.map(({ key, name }) => ({ key, name })))
                } else {
                    setSearch('')
                }
            }}
        >
            <PopoverTrigger
                render={
                    <Button
                        size="sm"
                        className="TodayPulse__edit"
                        aria-label="Edit numbers"
                        data-attr="today-pulse-edit"
                    >
                        <IconPencil />
                        Edit
                    </Button>
                }
            />
            <PopoverContent side="bottom" align="end" sideOffset={6} className="w-72 gap-1 p-1">
                <InputGroup className="h-7">
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                    <InputGroupInput
                        autoFocus
                        placeholder="Search insights to pin"
                        aria-label="Search insights to pin"
                        value={search}
                        onChange={(event) => {
                            setSearch(event.target.value)
                            loadPulseInsightResults(event.target.value)
                        }}
                    />
                </InputGroup>
                <ul className="m-0 flex max-h-72 list-none flex-col overflow-y-auto scroll-mask-y-4 scroll-py-4 p-0">
                    {rows.map((metric) => {
                        const pinned = isPinned(metric.key)
                        return (
                            <PulsePinRow
                                key={metric.key}
                                metric={metric}
                                pinned={pinned}
                                disabledReason={
                                    full && !pinned ? `You can pin ${PULSE_TILES}. Unpin one first.` : undefined
                                }
                                onToggle={() => toggle(metric)}
                            />
                        )
                    })}
                </ul>
                {searching && rows.length === 0 ? (
                    <Text size="xs" render={<p />} className="m-0 px-2 py-1.5 text-muted-foreground">
                        {pulseInsightResultsLoading ? 'Searching…' : 'No trends or SQL insights match your search'}
                    </Text>
                ) : null}
                <div className="flex min-h-7 items-center justify-between gap-2 border-t border-border px-2 pt-1">
                    <Text size="xs" render={<span />} className="text-muted-foreground">
                        Pins stay. Suggestions fill the rest.
                    </Text>
                    {pinnedPulseMetrics.length > 0 ? (
                        <Text size="xs" render={<span />} className="shrink-0 text-muted-foreground">
                            <Button
                                size="inline"
                                variant="link-muted"
                                className="font-normal"
                                onClick={() => setPinnedPulseKeys([])}
                                data-attr="today-pulse-unpin-all"
                            >
                                Unpin all
                            </Button>
                        </Text>
                    ) : null}
                </div>
            </PopoverContent>
        </Popover>
    )
}
