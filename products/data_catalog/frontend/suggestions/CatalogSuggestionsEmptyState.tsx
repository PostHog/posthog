import { useActions, useValues } from 'kea'

import * as floatPng from '@posthog/brand/hoggies/png/float'
import * as mailboxPng from '@posthog/brand/hoggies/png/mailbox'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

import { waitingSuggestionsText } from 'products/warehouse_suggestions/frontend/suggestionCopy'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

const HedgehogFloat = pngHoggie(floatPng)
const HedgehogMailbox = pngHoggie(mailboxPng)

export function CatalogSuggestionsEmptyState(): JSX.Element {
    const { status, showingMore } = useValues(warehouseSuggestionsLogic)
    const { showMore } = useActions(warehouseSuggestionsLogic)

    if (status?.can_show_more) {
        return (
            <Empty tabIndex={-1} data-suggestions-done className="py-10">
                <EmptyHeader>
                    <EmptyMedia>
                        <HedgehogMailbox className="w-32" />
                    </EmptyMedia>
                    <EmptyTitle>You're done for today</EmptyTitle>
                    <EmptyDescription>
                        {`${waitingSuggestionsText(status.waiting)} New ones show up each day, or you can review them now.`}
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button
                        variant="outline"
                        loading={showingMore}
                        onClick={() => showMore('section')}
                        data-attr="warehouse-suggestions-show-more"
                    >
                        Show more suggestions
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }
    return (
        <Empty tabIndex={-1} data-suggestions-done className="py-10">
            <EmptyHeader>
                <EmptyMedia>
                    <HedgehogFloat className="w-32" />
                </EmptyMedia>
                <EmptyTitle>All caught up</EmptyTitle>
                <EmptyDescription>
                    Suggestions come from how people read your tables and views. When usage changes, new ones show up
                    here.
                </EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}
