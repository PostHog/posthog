import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { BetsOverviewApi } from '../generated/api.schemas'
import { money } from '../lib/format'
import { BetsTreemap } from './BetsTreemap'

export function BetsAllocation({ overview }: { overview: BetsOverviewApi }): JSX.Element {
    const [open, setOpen] = useState(false)
    const [selected, setSelected] = useState<string | null>(null)
    const fundedBets = overview.bets.filter((bet) => bet.money.allocated_cents > 0)
    const areas = new Map<string, number>()
    fundedBets.forEach((bet) =>
        areas.set(bet.area || 'Unassigned', (areas.get(bet.area || 'Unassigned') ?? 0) + bet.money.allocated_cents)
    )
    const items = [
        ...Array.from(areas, ([area, value]) => ({ id: area, label: area, value, detail: money(value) })),
        {
            id: '__available',
            label: 'Available',
            value: overview.unallocated_cents,
            detail: money(overview.unallocated_cents),
        },
    ].filter((item) => item.value > 0)
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <section className="flex min-w-0 items-center justify-between gap-6" aria-label="Budget allocation">
                <div className="flex flex-col gap-1 items-start min-w-0">
                    <PopoverTrigger render={<Button variant="link-muted" size="inline" />}>
                        Budget allocation <IconArrowRight />
                    </PopoverTrigger>
                    <span className="Bets__value tabular-nums">{money(overview.settings.budget_cents)}</span>
                    <Text
                        size="xs"
                        variant="muted"
                    >{`${money(overview.allocated_cents)} allocated · ${money(overview.unallocated_cents)} available`}</Text>
                </div>
                {!!items.length && (
                    <div className="Bets__allocationPreview w-40 shrink-0">
                        <BetsTreemap
                            items={items}
                            onSelect={(id) => {
                                setSelected(id)
                                setOpen(true)
                            }}
                            label="Explore budget allocation"
                        />
                    </div>
                )}
            </section>
            <PopoverContent
                align="start"
                className="Today__page Bets w-[480px] max-w-[calc(100vw-40px)] max-h-[min(600px,var(--available-height))] overflow-y-auto p-5"
                aria-label="Budget allocation by product area"
            >
                <h2 className="Bets__sectionTitle">Budget allocation</h2>
                <BetsTreemap items={items} selected={selected} onSelect={setSelected} label="Budget by product area" />
                <div className="flex flex-col gap-1" aria-label="Allocation by area">
                    {items.map((item) => (
                        <Button
                            key={item.id}
                            variant={selected === item.id ? 'secondary' : 'default'}
                            size="sm"
                            className="w-full justify-between"
                            aria-pressed={selected === item.id}
                            onClick={() => setSelected(selected === item.id ? null : item.id)}
                        >
                            <span className="truncate">{item.label}</span>
                            <span className="tabular-nums">{item.detail}</span>
                        </Button>
                    ))}
                </div>
                {selected && selected !== '__available' && (
                    <div
                        className="flex flex-col gap-2 pt-3 border-t border-primary"
                        aria-label={`Bets in ${selected}`}
                    >
                        {fundedBets
                            .filter((bet) => (bet.area || 'Unassigned') === selected)
                            .map((bet) => (
                                <Button
                                    key={bet.id}
                                    variant="link-muted"
                                    size="sm"
                                    className="w-full justify-between"
                                    render={<LinkPrimitive to={urls.bet(bet.id)} />}
                                >
                                    <span className="truncate">{bet.title}</span>
                                    <span className="shrink-0 tabular-nums">{money(bet.money.allocated_cents)}</span>
                                </Button>
                            ))}
                    </div>
                )}
                {overview.can_edit && (
                    <Button variant="link-muted" render={<LinkPrimitive to={urls.betsSettings()} />}>
                        Manage budget <IconArrowRight />
                    </Button>
                )}
            </PopoverContent>
        </Popover>
    )
}
