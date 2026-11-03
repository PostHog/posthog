import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronDown, IconWarning } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { FilterLogicalOperator } from '~/types'

import { FilterBarAddMenu } from './FilterBarAddMenu'
import { FilterBarChip } from './FilterBarChip'
import { fieldFromFilter } from './filterBarFields'
import { FilterBarGroupMenu } from './FilterBarGroupMenu'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarNodeChip } from './FilterBarNodeChip'
import { contradictsEarlierSibling, isEventNode, isGroupNode, isItemNode } from './filterBarTree'
import { FilterBarEventNode, FilterBarGroupNode, FilterBarNode } from './filterBarTypes'

const OPERATOR_LABELS: Record<FilterLogicalOperator, string> = {
    [FilterLogicalOperator.And]: 'and',
    [FilterLogicalOperator.Or]: 'or',
}

/**
 * The word that starts a row: "Where", then the operator. Only the second row's word is a control, because one
 * operator joins every row of a group, so the rest repeat it.
 */
function RowConnector({
    index,
    type,
    onTypeChange,
}: {
    index: number
    type: FilterLogicalOperator
    onTypeChange?: (type: FilterLogicalOperator) => void
}): JSX.Element {
    if (index === 0 || index > 1 || !onTypeChange) {
        return (
            <span className={index === 0 ? undefined : 'px-2 text-muted-foreground'}>
                {index === 0 ? 'Where' : OPERATOR_LABELS[type]}
            </span>
        )
    }
    return (
        <DropdownMenu modal={false}>
            <DropdownMenuTrigger
                render={<Button variant="outline" className="w-full justify-between" />}
                data-attr="filter-bar-group-operator"
            >
                {OPERATOR_LABELS[type]}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuRadioGroup
                    value={type}
                    onValueChange={(value) => onTypeChange(value as FilterLogicalOperator)}
                >
                    <DropdownMenuRadioItem value={FilterLogicalOperator.And}>and</DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value={FilterLogicalOperator.Or}>or</DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/** The connector column keeps every chip, and the add button under them, on one left edge. */
function StackedRow({ connector, children }: { connector?: ReactNode; children: ReactNode }): JSX.Element {
    return (
        <div className="flex items-start gap-2" data-attr={connector ? 'filter-bar-stacked-row' : undefined}>
            <div className="flex h-7 w-16 shrink-0 items-center">{connector}</div>
            <div className="min-w-0 flex-1">{children}</div>
        </div>
    )
}

function GroupPanel({ group, depth }: { group: FilterBarGroupNode; depth: number }): JSX.Element {
    const { setGroupType } = useActions(filterBarLogic)
    const isOr = group.type === FilterLogicalOperator.Or
    return (
        <div
            role="group"
            aria-label={isOr ? 'Any of these filters' : 'All of these filters'}
            className="flex flex-col gap-1.5 rounded-md border border-border px-2 pb-2"
            data-attr="filter-bar-group"
        >
            <div className="-mt-px flex items-center justify-between">
                <span className="text-muted-foreground">{isOr ? 'Match any' : 'Match all'}</span>
                <FilterBarGroupMenu groupId={group.id} />
            </div>
            <FilterBarStackedRows
                rows={group.children}
                type={group.type}
                depth={depth + 1}
                onTypeChange={(type) => setGroupType(group.id, type)}
            />
            <StackedRow>
                <FilterBarAddMenu targetId={group.id} label="Add filter" />
            </StackedRow>
        </div>
    )
}

/** An event's property filters are one AND list, so these rows offer no operator and no grouping. */
function EventRows({ node, depth }: { node: FilterBarEventNode; depth: number }): JSX.Element {
    const { addTargetId, menuOpen } = useValues(filterBarLogic)
    const adding = menuOpen && addTargetId === node.id
    return (
        <div className="flex flex-col gap-1.5">
            <FilterBarNodeChip node={node} parentType={FilterLogicalOperator.And} depth={depth} />
            {node.items.map((item, index) => (
                <div key={item.id} className="flex items-start gap-2" data-attr="filter-bar-event-property">
                    <div
                        aria-hidden
                        className="ms-2 h-3.5 w-3 shrink-0 rounded-es-sm border-b border-s border-border"
                    />
                    <span className="flex h-7 shrink-0 items-center text-muted-foreground">
                        {index === 0 ? 'with' : 'and'}
                    </span>
                    <FilterBarChip item={item} />
                </div>
            ))}
            {adding && (
                <div className="ms-7">
                    <FilterBarAddMenu targetId={node.id} label="Add filter" />
                </div>
            )}
        </div>
    )
}

function ContradictionWarning({ label }: { label: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                render={<span className="ms-1.5 inline-flex h-7 shrink-0 items-center text-warning-foreground" />}
                aria-label={`${label} can't match two different values at once`}
                data-attr="filter-bar-contradiction"
            >
                <IconWarning />
            </TooltipTrigger>
            <TooltipContent>{label} can't be two different values at once, so this matches nothing.</TooltipContent>
        </Tooltip>
    )
}

/** Rows that read as one sentence from the top: "Where A, and B, and any of (C, D)". */
export function FilterBarStackedRows({
    rows,
    type,
    depth,
    onTypeChange,
}: {
    rows: FilterBarNode[]
    type: FilterLogicalOperator
    depth: number
    onTypeChange?: (type: FilterLogicalOperator) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            {rows.map((row, index) => (
                <StackedRow
                    key={row.id}
                    connector={<RowConnector index={index} type={type} onTypeChange={onTypeChange} />}
                >
                    {isGroupNode(row) ? (
                        <GroupPanel group={row} depth={depth} />
                    ) : isEventNode(row) ? (
                        <EventRows node={row} depth={depth} />
                    ) : (
                        <div className="flex items-start">
                            <FilterBarNodeChip node={row} parentType={type} depth={depth} />
                            {isItemNode(row) && contradictsEarlierSibling(rows, index, type) && (
                                <ContradictionWarning label={fieldFromFilter(row.filter)?.label ?? 'This filter'} />
                            )}
                        </div>
                    )}
                </StackedRow>
            ))}
        </div>
    )
}
