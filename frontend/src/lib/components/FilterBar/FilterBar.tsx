import { BindLogic, useActions, useValues } from 'kea'
import { ReactNode, useCallback, useMemo, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'
import { Button, ButtonGroup, cn } from '@posthog/quill'

import { FilterLogicalOperator } from '~/types'

import { FilterBarAddMenu } from './FilterBarAddMenu'
import { FilterBarControlsContext, FilterBarControlsContextValue, useFilterBarControls } from './filterBarControls'
import { FilterBarLogicProps, filterBarLogic } from './filterBarLogic'
import { FilterBarNodeChip } from './FilterBarNodeChip'
import { FilterBarSqlDialog } from './FilterBarSqlDialog'
import { FilterBarStackedEditor } from './FilterBarStackedEditor'
import { isGroupNode } from './filterBarTree'
import { FilterBarControl, FilterBarEventNode, FilterBarItem } from './filterBarTypes'

export type FilterBarProps = FilterBarLogicProps & {
    className?: string
    children?: ReactNode
    /** Controls after the filter chips, for ones that shape results rather than narrow them, such as `FilterBarBreakdown`. */
    trailing?: ReactNode
    actions?: ReactNode
    /** Shows in the stacked editor's footer, for what only the surface knows, such as how many people match. */
    stackedFooter?: ReactNode
}

/**
 * The filter bar: an add button that opens the field picker, one chip per filter, and a clear button once any
 * filter is on. The complete filters flow to `onChange`; a chip that still waits for a value stays local.
 * A surface that stores groups passes `filterGroup` and `onFilterGroupChange` instead, and people can then build OR
 * branches. Past three filters, or with any nesting, one summary chip opens every filter stacked. `categoryIds` opts such a surface in to `events` and to categories it registered.
 *
 * Children that call `useFilterBarControl` join the bar: they render their own chip, get a row in the add menu while
 * they have no value, and reset with the clear button.
 */
export function FilterBar({
    className,
    children,
    trailing,
    actions,
    stackedFooter,
    ...logicProps
}: FilterBarProps): JSX.Element {
    const controlsContext = useControlsRegistry()
    return (
        <BindLogic logic={filterBarLogic} props={logicProps}>
            <FilterBarControlsContext.Provider value={controlsContext}>
                <FilterBarContent
                    className={className}
                    trailing={trailing}
                    actions={actions}
                    stackedFooter={stackedFooter}
                >
                    {children}
                </FilterBarContent>
            </FilterBarControlsContext.Provider>
        </BindLogic>
    )
}

function useControlsRegistry(): FilterBarControlsContextValue {
    const [controls, setControls] = useState<FilterBarControl[]>([])
    // A control registers again when its value state changes. The first position it took keeps the menu order stable.
    const order = useRef(new Map<string, number>())

    const register = useCallback((control: FilterBarControl) => {
        if (!order.current.has(control.id)) {
            order.current.set(control.id, order.current.size)
        }
        const position = (entry: FilterBarControl): number => order.current.get(entry.id) ?? 0
        setControls((current) =>
            [...current.filter((entry) => entry.id !== control.id), control].sort((a, b) => position(a) - position(b))
        )
        return () => setControls((current) => current.filter((entry) => entry !== control))
    }, [])

    return useMemo(() => ({ controls, register }), [controls, register])
}

function FilterBarContent({
    className,
    children,
    trailing,
    actions,
    stackedFooter,
}: {
    className?: string
    children?: ReactNode
    trailing?: ReactNode
    actions?: ReactNode
    stackedFooter?: ReactNode
}): JSX.Element {
    const { nodes, showsStackedEditor } = useValues(filterBarLogic)
    const { clearItems } = useActions(filterBarLogic)
    const controls = useFilterBarControls()
    const controlsWithValue = controls.filter((control) => control.hasValue)

    return (
        <div data-quill className={cn('flex min-w-0 flex-wrap items-center gap-1.5', className)} data-attr="filter-bar">
            <FilterBarAddMenu />
            {children}
            {showsStackedEditor ? (
                <FilterBarStackedEditor footer={stackedFooter} />
            ) : (
                nodes
                    .filter((node): node is FilterBarItem | FilterBarEventNode => !isGroupNode(node))
                    .map((node) => (
                        <FilterBarNodeChip key={node.id} node={node} parentType={FilterLogicalOperator.And} depth={0} />
                    ))
            )}
            {trailing}
            <ButtonGroup className="ms-auto empty:hidden">
                {(nodes.length > 0 || controlsWithValue.length > 0) && (
                    <Button
                        variant="destructive-outline"
                        onClick={() => {
                            clearItems()
                            controlsWithValue.forEach((control) => control.clear())
                        }}
                        data-attr="filter-bar-clear"
                    >
                        <IconX />
                        Clear
                    </Button>
                )}
                {actions}
            </ButtonGroup>
            <FilterBarSqlDialog />
        </div>
    )
}
