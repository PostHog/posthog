import { IconArrowRight } from '@posthog/icons'
import { Button, Dialog, DialogTrigger, Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import type { BetsOverviewApi } from '../generated/api.schemas'
import { money } from '../lib/format'
import { BetsAllocationDialog } from './BetsAllocationDialog'
import { BetsTreemap, type BetsTreemapItem } from './BetsTreemap'

export function BetsAllocation({ overview }: { overview: BetsOverviewApi }): JSX.Element {
    const items: BetsTreemapItem[] = [
        ...overview.bets.map((bet) => ({
            id: bet.id,
            label: bet.title,
            value: bet.money.allocated_cents,
            amount: money(bet.money.allocated_cents),
            to: urls.bet(bet.id),
        })),
        {
            id: '__available',
            label: 'Available',
            value: overview.unallocated_cents,
            amount: money(overview.unallocated_cents),
            to: overview.can_edit ? urls.betsSettings() : undefined,
            available: true,
        },
    ].filter((item) => item.value > 0)
    return (
        <Dialog>
            <section className="flex min-w-0 items-center justify-between gap-6" aria-label="Budget allocation">
                <div className="flex flex-col gap-1 items-start min-w-0">
                    <DialogTrigger render={<Button variant="link-muted" size="inline" />}>
                        Budget allocation <IconArrowRight />
                    </DialogTrigger>
                    <span className="Bets__value tabular-nums">{money(overview.settings.budget_cents)}</span>
                    <Text
                        size="xs"
                        variant="muted"
                    >{`${money(overview.allocated_cents)} allocated · ${money(overview.unallocated_cents)} available`}</Text>
                </div>
                {!!items.length && (
                    <DialogTrigger
                        className="Bets__allocationPreview w-40 shrink-0"
                        aria-label="Open budget allocation"
                        data-attr="bets-allocation-preview"
                    >
                        <BetsTreemap items={items.map(({ to, ...item }) => item)} label="Budget allocation preview" />
                    </DialogTrigger>
                )}
            </section>
            <BetsAllocationDialog overview={overview} items={items} />
        </Dialog>
    )
}
