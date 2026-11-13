import type { ReactNode } from 'react'

import { IconChevronDown, IconFilter } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Separator, Text } from '@posthog/quill'

import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'

interface QuillDashboardPropertyFiltersProps {
    addFilter: ReactNode
    activeFilters: JSX.Element[]
    clearFilters: () => void
}

export function QuillDashboardPropertyFilters({
    addFilter,
    activeFilters,
    clearFilters,
}: QuillDashboardPropertyFiltersProps): JSX.Element {
    if (activeFilters.length === 0) {
        return <>{addFilter}</>
    }

    const countLabel = activeFilters.length === 1 ? '1 filter' : `${activeFilters.length} filters`

    return (
        <Popover
            modal={false}
            onOpenChange={(open, details) => {
                if (closesIntoLemonPopover(open, details)) {
                    details.cancel()
                }
            }}
        >
            <PopoverTrigger render={<Button variant="outline" />} data-attr="dashboard-filters-stacked-trigger">
                <IconFilter />
                <span>{countLabel}</span>
                <IconChevronDown />
            </PopoverTrigger>
            <PopoverContent
                align="start"
                className="w-auto min-w-80 max-w-[min(40rem,90vw)] gap-0 p-0"
                data-attr="dashboard-filters-stacked-editor"
            >
                <div className="flex items-center justify-between gap-4 px-3 pt-2">
                    <Text size="sm" render={<span />}>
                        <span className="font-semibold">Filters</span>
                        <span className="text-muted-foreground"> · {countLabel}</span>
                    </Text>
                    <Button onClick={clearFilters} data-attr="dashboard-filters-stacked-clear">
                        Clear all
                    </Button>
                </div>
                <div className="flex max-h-[60vh] flex-col items-start gap-2 overflow-y-auto p-3">{activeFilters}</div>
                <Separator />
                <div className="p-2">{addFilter}</div>
            </PopoverContent>
        </Popover>
    )
}
