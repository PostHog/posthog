import { ReactElement, ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { IconArrowLeft, IconFilter } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

import { FilterPickerNode, FilterPickerPath } from './FilterPicker.types'
import { useFilterPickerNavigation } from './useFilterPickerNavigation'

const SCROLL_PANEL_CLASSNAME = 'max-h-[22rem] overflow-y-auto overflow-x-hidden'

export interface FilterPickerProps {
    rootNodes: FilterPickerNode[]
    trigger: ReactElement
    initialPath?: FilterPickerPath
    rootSearchPlaceholder?: string
    onOpenChange?: (open: boolean) => void
    open?: boolean
    emptyMessage?: ReactNode
}

interface SectionGroup {
    sectionKey: string
    sectionLabel?: ReactNode
    sectionIcon?: ReactNode
    nodes: FilterPickerNode[]
}

function groupNodesBySection(nodes: FilterPickerNode[]): SectionGroup[] {
    const groups: SectionGroup[] = []
    for (const node of nodes) {
        const sectionKey = node.section?.id ?? '__ungrouped__'
        const lastGroup = groups[groups.length - 1]
        if (lastGroup?.sectionKey === sectionKey) {
            lastGroup.nodes.push(node)
        } else {
            groups.push({
                sectionKey,
                sectionLabel: node.section?.label,
                sectionIcon: node.section?.icon,
                nodes: [node],
            })
        }
    }
    return groups
}

export function FilterPicker({
    rootNodes,
    trigger,
    initialPath,
    rootSearchPlaceholder = 'Search filters…',
    onOpenChange,
    open: controlledOpen,
    emptyMessage = 'No matches',
}: FilterPickerProps): JSX.Element {
    const [internalOpen, setInternalOpen] = useState(false)
    const open = controlledOpen ?? internalOpen
    const setOpen = (nextOpen: boolean): void => {
        if (controlledOpen === undefined) {
            setInternalOpen(nextOpen)
        }
        onOpenChange?.(nextOpen)
    }

    const navigation = useFilterPickerNavigation({ rootNodes, initialPath, rootSearchPlaceholder, open })
    const close = (): void => setOpen(false)

    // Structure (getChildren) is pure; this is where the active node's content is allowed to load.
    const { activeNode, query, activePath } = navigation
    useEffect(() => {
        activeNode.loadContent?.({ query, path: activePath })
        // activeNode is rebuilt every render; key the effect on its stable id plus the query instead.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeNode.id, query])

    const breadcrumbParts = navigation.stack
        .filter((node) => node.id !== navigation.rootNode.id)
        .map((node) => node.breadcrumbLabel ?? node.tokenLabel ?? node.label)
    const breadcrumbTitle = breadcrumbParts.filter((part): part is string => typeof part === 'string').join(' ')

    const childrenResult = navigation.activeNode.getChildren?.({
        query: navigation.query,
        path: navigation.activePath,
    }) ?? { nodes: [], isLoading: false }
    const groupedNodes = useMemo(() => groupNodesBySection(childrenResult.nodes), [childrenResult.nodes])

    const isPanel = navigation.activeNode.kind === 'panel' && !!navigation.activeNode.renderPanel

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={trigger} />
            <PopoverContent align="start" className={cn('gap-1 p-1', isPanel ? 'w-auto' : 'w-72')} sideOffset={4}>
                <SearchRow
                    value={navigation.query}
                    onChange={navigation.setQuery}
                    placeholder={navigation.activeNode.searchPlaceholder ?? rootSearchPlaceholder}
                    canGoBack={!navigation.isRoot}
                    onBack={navigation.goBack}
                />
                {breadcrumbParts.length > 0 && (
                    <div className="truncate px-2 py-1 text-sm font-medium text-primary" title={breadcrumbTitle}>
                        {breadcrumbParts.map((part, index) => (
                            <span key={index}>
                                {index > 0 && ' '}
                                {part}
                            </span>
                        ))}
                    </div>
                )}
                <div className="-mx-1 my-1 h-px bg-border" />
                {isPanel && navigation.activeNode.renderPanel ? (
                    <div onKeyDown={(event) => event.stopPropagation()}>
                        {navigation.activeNode.renderPanel({
                            close,
                            resetToRoot: navigation.resetToRoot,
                            path: navigation.activePath,
                            query: navigation.query,
                            setQuery: navigation.setQuery,
                        })}
                    </div>
                ) : (
                    <div
                        data-filter-picker-results
                        className={SCROLL_PANEL_CLASSNAME}
                        onScroll={(event) => {
                            const target = event.currentTarget
                            const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight
                            if (distanceFromBottom < 48 && childrenResult.hasMore && !childrenResult.isLoadingMore) {
                                childrenResult.loadMore?.()
                            }
                        }}
                    >
                        {childrenResult.isLoading && !childrenResult.nodes.length ? (
                            <div className="px-2 py-1.5 text-xs text-tertiary">Loading…</div>
                        ) : !childrenResult.nodes.length ? (
                            <div className="px-2 py-1.5 text-xs text-tertiary">
                                {childrenResult.emptyMessage ?? emptyMessage}
                            </div>
                        ) : (
                            <>
                                {groupedNodes.map((group, sectionIndex) => (
                                    <div key={group.sectionKey}>
                                        {sectionIndex > 0 && <div className="my-1 h-px bg-border" />}
                                        {group.sectionLabel && (
                                            <div className="flex items-center gap-1.5 px-2 py-1.5 text-xs font-semibold text-tertiary [&_svg]:size-3.5">
                                                {group.sectionIcon}
                                                <span>{group.sectionLabel}</span>
                                            </div>
                                        )}
                                        {group.nodes.map((node) => (
                                            <FilterPickerItem
                                                key={node.id}
                                                node={node}
                                                close={close}
                                                openNode={navigation.openNode}
                                                resetToRoot={navigation.resetToRoot}
                                                path={navigation.activePath}
                                            />
                                        ))}
                                    </div>
                                ))}
                                {childrenResult.isLoadingMore && (
                                    <div className="px-2 py-1.5 text-xs text-tertiary">Loading more…</div>
                                )}
                                {childrenResult.hasMore && childrenResult.loadMore && !childrenResult.isLoadingMore && (
                                    <div className="p-1">
                                        <Button
                                            size="sm"
                                            variant="outline"
                                            className="w-full"
                                            onClick={childrenResult.loadMore}
                                        >
                                            Load more
                                        </Button>
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                )}
            </PopoverContent>
        </Popover>
    )
}

function FilterPickerItem({
    node,
    close,
    openNode,
    resetToRoot,
    path,
}: {
    node: FilterPickerNode
    close: () => void
    openNode: (node: FilterPickerNode) => void
    resetToRoot: () => void
    path: FilterPickerPath
}): JSX.Element {
    const isBranch = node.kind === 'branch' || node.kind === 'panel'

    return (
        <button
            type="button"
            disabled={!!node.disabledReason}
            aria-disabled={!!node.disabledReason}
            title={node.disabledReason}
            className="flex w-full items-center rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-fill-button-tertiary-hover focus:bg-fill-button-tertiary-hover disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => {
                if (node.disabledReason) {
                    return
                }
                if (isBranch) {
                    openNode(node)
                    return
                }
                node.onSelect?.({
                    close: () => {
                        resetToRoot()
                        close()
                    },
                    resetToRoot,
                    path,
                })
            }}
        >
            <span className="min-w-0 flex-1 truncate">{node.label}</span>
            {node.hint && <span className="ml-auto pl-2 text-xxs uppercase text-tertiary">{node.hint}</span>}
        </button>
    )
}

function SearchRow({
    value,
    onChange,
    placeholder,
    canGoBack,
    onBack,
}: {
    value: string
    onChange: (value: string) => void
    placeholder: string
    canGoBack: boolean
    onBack: () => void
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        const raf = requestAnimationFrame(() => inputRef.current?.focus())
        return () => cancelAnimationFrame(raf)
    }, [])

    return (
        <div className="flex h-7 items-center gap-1.5 rounded-md border border-transparent bg-[var(--color-bg-fill-button-tertiary)] px-1.5 text-sm">
            {canGoBack ? (
                <button
                    type="button"
                    aria-label="Go back to previous filter level"
                    className="shrink-0 text-tertiary hover:text-primary"
                    onClick={(event) => {
                        event.preventDefault()
                        event.stopPropagation()
                        onBack()
                    }}
                >
                    <IconArrowLeft className="text-base" />
                </button>
            ) : (
                <IconFilter aria-hidden className="shrink-0 text-base text-tertiary" />
            )}
            <input
                ref={inputRef}
                type="text"
                aria-label="Search filters"
                className={cn(
                    'min-w-0 flex-1 border-0 bg-transparent p-0 text-sm outline-none placeholder:text-tertiary'
                )}
                placeholder={placeholder}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'ArrowDown') {
                        const popup = event.currentTarget.closest('[data-slot="popover-content"]')
                        const results = popup?.querySelector<HTMLElement>('[data-filter-picker-results]')
                        const firstItem = results?.querySelector<HTMLElement>('button:not(:disabled)')
                        if (firstItem) {
                            event.preventDefault()
                            event.stopPropagation()
                            firstItem.focus()
                        }
                        return
                    }
                    if (!['Escape', 'Tab', 'ArrowUp', 'Enter'].includes(event.key)) {
                        event.stopPropagation()
                    }
                }}
            />
        </div>
    )
}
