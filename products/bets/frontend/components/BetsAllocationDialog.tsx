import { IconArrowRight } from '@posthog/icons'
import {
    Button,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { BetsOverviewApi } from '../generated/api.schemas'
import { money } from '../lib/format'
import { BetsTreemap, type BetsTreemapItem } from './BetsTreemap'

export function BetsAllocationDialog({
    overview,
    items,
}: {
    overview: BetsOverviewApi
    items: BetsTreemapItem[]
}): JSX.Element {
    return (
        <DialogContent className="Today__page Bets BetsAllocationDialog" size="wide">
            <DialogHeader>
                <DialogTitle>Budget allocation</DialogTitle>
                <DialogDescription>
                    {`${money(overview.settings.budget_cents)} budget · ${money(overview.allocated_cents)} allocated · ${money(overview.unallocated_cents)} available`}
                </DialogDescription>
            </DialogHeader>
            <DialogBody>
                {items.length ? (
                    <BetsTreemap items={items} label="Budget by bet" />
                ) : (
                    <Text size="sm" variant="muted">
                        No budget is allocated yet.
                    </Text>
                )}
            </DialogBody>
            {overview.can_edit && (
                <DialogFooter>
                    <Button variant="link-muted" render={<LinkPrimitive to={urls.betsSettings()} />}>
                        Manage budget <IconArrowRight />
                    </Button>
                </DialogFooter>
            )}
        </DialogContent>
    )
}
