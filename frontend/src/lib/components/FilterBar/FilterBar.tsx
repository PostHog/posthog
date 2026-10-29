import { BindLogic, useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { FilterBarAddMenu } from './FilterBarAddMenu'
import { FilterBarChip } from './FilterBarChip'
import { FilterBarLogicProps, filterBarLogic } from './filterBarLogic'
import { FilterBarSqlDialog } from './FilterBarSqlDialog'

export interface FilterBarProps extends FilterBarLogicProps {
    className?: string
}

/**
 * The filter bar: an add button that opens the field picker, one chip per filter, and a clear button once any
 * filter is on. The complete filters flow to `onChange`; a chip that still waits for a value stays local.
 */
export function FilterBar({ className, ...logicProps }: FilterBarProps): JSX.Element {
    return (
        <BindLogic logic={filterBarLogic} props={logicProps}>
            <FilterBarContent className={className} />
        </BindLogic>
    )
}

function FilterBarContent({ className }: { className?: string }): JSX.Element {
    const { items } = useValues(filterBarLogic)
    const { clearItems } = useActions(filterBarLogic)

    return (
        <div data-quill className={cn('flex min-w-0 flex-wrap items-center gap-1.5', className)} data-attr="filter-bar">
            <FilterBarAddMenu />
            {items.map((item) => (
                <FilterBarChip key={item.id} item={item} />
            ))}
            {items.length > 0 && (
                <Button variant="link-muted" onClick={clearItems} data-attr="filter-bar-clear">
                    <IconX />
                    Clear
                </Button>
            )}
            <FilterBarSqlDialog />
        </div>
    )
}
