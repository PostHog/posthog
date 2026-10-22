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
    cn,
} from '@posthog/quill'

import type { PulsePinApi } from 'products/today/frontend/generated/api.schemas'

import { PULSE_TILES, pulsePinLimitReason, todayHighlightsLogic } from './todayHighlightsLogic'

function PulsePinRow({
    metric,
    pinned,
    disabledReason,
    onToggle,
}: {
    metric: PulsePinApi
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
    const {
        pulsePins,
        pulseTiles,
        pulseInsightResults,
        pulseInsightResultsLoading,
        pulseInsightSearchFailed,
        pulsePinsUnavailableReason,
    } = useValues(todayHighlightsLogic)
    const { togglePulsePin, loadPulseInsightResults, pulseEditorOpened } = useActions(todayHighlightsLogic)
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const [shownOnOpen, setShownOnOpen] = useState<PulsePinApi[]>([])

    const isPinned = (key: string): boolean => pulsePins.some((pinned) => pinned.key === key)
    const searching = search.trim().length > 0
    const shownNow = [...shownOnOpen, ...pulsePins.filter((pin) => !shownOnOpen.some((shown) => shown.key === pin.key))]
    const rows = !searching
        ? shownNow
        : pulseInsightResultsLoading || pulseInsightSearchFailed
          ? []
          : pulseInsightResults

    return (
        <Popover
            open={open}
            onOpenChange={(next) => {
                setOpen(next)
                if (next) {
                    pulseEditorOpened()
                    setShownOnOpen(pulseTiles.map(({ key, name, dashboard_id }) => ({ key, name, dashboard_id })))
                } else {
                    setSearch('')
                }
            }}
        >
            <PopoverTrigger
                render={
                    <Button
                        size="sm"
                        className={cn('TodayPulse__edit', pulseTiles.length === 0 && 'TodayPulse__edit--shown')}
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
                            if (event.target.value.trim()) {
                                loadPulseInsightResults(event.target.value)
                            }
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
                                    pulsePinsUnavailableReason ?? pulsePinLimitReason(pulsePins.length, pinned)
                                }
                                onToggle={() => togglePulsePin(metric, 'editor')}
                            />
                        )
                    })}
                </ul>
                {searching && rows.length === 0 ? (
                    <Text size="xs" render={<p />} className="m-0 px-2 py-1.5 text-muted-foreground">
                        {pulseInsightResultsLoading
                            ? 'Searching…'
                            : pulseInsightSearchFailed
                              ? "Couldn't search your insights. Try again."
                              : 'No insights you can pin match your search'}
                    </Text>
                ) : null}
                {pulsePins.length >= PULSE_TILES ? (
                    <Text size="xs" render={<p />} className="m-0 px-2 py-1.5 text-muted-foreground">
                        {PULSE_TILES} pinned. Unpin one to pin another.
                    </Text>
                ) : null}
            </PopoverContent>
        </Popover>
    )
}
