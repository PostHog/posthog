import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronDown, IconPlus } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Separator } from '@posthog/quill'

import { cohortsModel } from '~/models/cohortsModel'
import { FilterLogicalOperator } from '~/types'

import { FilterBarAddMenu } from './FilterBarAddMenu'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarStackedRows } from './FilterBarStackedRows'
import { filterBarSummary } from './filterBarSummary'
import { conditionCount, isGroupNode } from './filterBarTree'

function conditionLabel(count: number): string {
    return count === 1 ? '1 condition' : `${count} conditions`
}

/**
 * Filters past what a row of chips can show, as one summary chip that opens every filter stacked. A lone group at the
 * top is the whole filter, so it shows as the top-level rows and not as a panel inside them.
 */
export function FilterBarStackedEditor({ footer }: { footer?: ReactNode }): JSX.Element {
    const { nodes, stackedOpen, menuOpen, groupsEnabled } = useValues(filterBarLogic)
    const { cohortsById } = useValues(cohortsModel)
    const { setStackedOpen, setGroupType, setTopLevelType, clearItems, addGroup } = useActions(filterBarLogic)
    const onlyGroup = nodes.length === 1 && isGroupNode(nodes[0]) ? nodes[0] : null
    const count = conditionCount(nodes)

    return (
        <Popover
            modal={false}
            open={stackedOpen}
            onOpenChange={(open) => {
                // A row's add menu renders outside the popover, so a click in it reads as a click away.
                if (open || !menuOpen) {
                    setStackedOpen(open)
                }
            }}
        >
            <PopoverTrigger render={<Button variant="outline" />} data-attr="filter-bar-stacked-trigger">
                {conditionLabel(count)}
                <IconChevronDown />
            </PopoverTrigger>
            <PopoverContent
                align="start"
                className="w-auto max-h-[70vh] max-w-[min(48rem,90vw)] min-w-96 gap-0 overflow-hidden p-0"
                data-attr="filter-bar-stacked-editor"
            >
                <div className="flex items-center justify-between gap-4 px-3 pt-2">
                    <span>
                        <span className="font-semibold">Filters</span>
                        <span className="text-muted-foreground"> · {conditionLabel(count)}</span>
                    </span>
                    <Button
                        onClick={() => {
                            clearItems()
                            setStackedOpen(false)
                        }}
                        data-attr="filter-bar-stacked-clear"
                    >
                        Clear all
                    </Button>
                </div>
                <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 pt-2">
                    {count > 0 && (
                        <p className="m-0 rounded-md bg-muted p-2" data-attr="filter-bar-summary">
                            {filterBarSummary(nodes, cohortsById)}
                        </p>
                    )}
                    <FilterBarStackedRows
                        rows={onlyGroup ? onlyGroup.children : nodes}
                        type={onlyGroup ? onlyGroup.type : FilterLogicalOperator.And}
                        depth={0}
                        onTypeChange={
                            !groupsEnabled
                                ? undefined
                                : onlyGroup
                                  ? (type) => setGroupType(onlyGroup.id, type)
                                  : setTopLevelType
                        }
                    />
                </div>
                <Separator />
                <div className="flex flex-wrap items-center gap-1.5 p-2">
                    <FilterBarAddMenu targetId={onlyGroup?.id ?? null} label="Add filter" />
                    {groupsEnabled && (
                        <Button onClick={() => addGroup(onlyGroup?.id ?? null)} data-attr="filter-bar-add-group">
                            <IconPlus />
                            Add group
                        </Button>
                    )}
                    {footer && <div className="ms-auto px-2 text-muted-foreground">{footer}</div>}
                </div>
            </PopoverContent>
        </Popover>
    )
}
