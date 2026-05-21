import { ReactNode, useEffect, useRef } from 'react'

import { Empty, EmptyHeader, EmptyTitle, ItemMenuItem, Spinner } from '@posthog/quill'

import { useGroupList, UseGroupListResult } from '../hooks/useGroupList'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroup } from '../types'
import { useTaxonomicFilterContext } from './context'

export interface TaxonomicFilterPanelProps {
    /** Override the row renderer. Receives item + per-row state. */
    renderRow?: (props: TaxonomicFilterRowRenderProps) => ReactNode
    /** Slot shown when the active list returns showEmptyState=true. */
    emptyState?: ReactNode
    /** Slot shown when the active list returns showLoadingState=true. */
    loadingState?: ReactNode
    className?: string
}

export interface TaxonomicFilterRowRenderProps {
    item: TaxonomicDefinitionTypes
    index: number
    isActive: boolean
    onSelect: () => void
    onMouseEnter: () => void
    group: TaxonomicFilterGroup
}

/** Renders the active group's items. Internally calls `useGroupList` for the
 *  active group AND registers its api with the orchestrator so keyboard
 *  navigation routes through this list. */
export function TaxonomicFilterPanel({
    renderRow,
    emptyState,
    loadingState,
    className,
}: TaxonomicFilterPanelProps): JSX.Element | null {
    const { activeGroup } = useTaxonomicFilterContext()
    if (!activeGroup) {
        return null
    }
    return (
        <TaxonomicFilterActivePanel
            key={activeGroup.type}
            group={activeGroup}
            renderRow={renderRow}
            emptyState={emptyState}
            loadingState={loadingState}
            className={className}
        />
    )
}

interface ActivePanelProps {
    group: TaxonomicFilterGroup
    renderRow?: (props: TaxonomicFilterRowRenderProps) => ReactNode
    emptyState?: ReactNode
    loadingState?: ReactNode
    className?: string
}

function TaxonomicFilterActivePanel({
    group,
    renderRow,
    emptyState,
    loadingState,
    className,
}: ActivePanelProps): JSX.Element {
    const { getGroupListInput, registerActiveList, selectItem } = useTaxonomicFilterContext()
    const list: UseGroupListResult = useGroupList(getGroupListInput(group))

    // Register this list as the keyboard target for as long as the panel
    // is mounted. We pass a stable getter (`useRef`-backed) instead of
    // the `list` object itself so the registration doesn't churn on
    // every render — `useGroupList` returns a fresh reference each
    // render, and registering it directly produced a brief null window
    // between cleanup and re-register that broke `selectSelected()`
    // under concurrent rendering.
    const listRef = useRef(list)
    listRef.current = list
    useEffect(() => {
        registerActiveList(() => listRef.current)
        return () => registerActiveList(null)
    }, [registerActiveList])

    if (list.showLoadingState) {
        return (
            <div className={className}>
                {loadingState !== undefined ? (
                    loadingState
                ) : (
                    <Empty>
                        <EmptyHeader>
                            <Spinner />
                            <EmptyTitle>Loading…</EmptyTitle>
                        </EmptyHeader>
                    </Empty>
                )}
            </div>
        )
    }

    if (list.showEmptyState) {
        return (
            <div className={className}>
                {emptyState !== undefined ? (
                    emptyState
                ) : (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>
                                {list.needsMoreSearchCharacters ? 'Type more to search' : 'No results'}
                            </EmptyTitle>
                        </EmptyHeader>
                    </Empty>
                )}
            </div>
        )
    }

    return (
        <div className={className} role="listbox" data-attr={`taxonomic-list-${group.type}`}>
            {list.items.map((item, index) => {
                const isActive = list.index === index
                const onSelect = (): void => {
                    const itemValue = group.getValue?.(item) ?? null
                    selectItem(group, itemValue, item)
                }
                const onMouseEnter = (): void => list.setIndex(index)
                if (renderRow) {
                    return <div key={index}>{renderRow({ item, index, isActive, onSelect, onMouseEnter, group })}</div>
                }
                return (
                    <ItemMenuItem
                        key={index}
                        size="sm"
                        role="option"
                        aria-selected={isActive}
                        data-attr={`taxonomic-row-${group.type}-${index}`}
                        onClick={onSelect}
                        onMouseEnter={onMouseEnter}
                    >
                        {group.getName?.(item) ?? ('name' in item ? (item as { name?: string }).name : '')}
                    </ItemMenuItem>
                )
            })}
        </div>
    )
}
