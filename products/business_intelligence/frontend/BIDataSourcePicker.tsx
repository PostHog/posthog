import { useActions, useMountedLogic, useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronDown, IconDatabase } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, Spinner } from '@posthog/lemon-ui'

import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'

import { biDataSourcePickerLogic } from 'products/business_intelligence/frontend/biDataSourcePickerLogic'
import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { getBIDataSourceKey } from 'products/business_intelligence/frontend/biEditorTypes'

export function BIDataSourcePicker(): JSX.Element {
    const biLogic = useMountedLogic(biEditorLogic)
    const logic = biDataSourcePickerLogic({ tabId: biLogic.props.tabId })
    const { config, databaseLoading, databaseLoadError, open, search, filteredTree, visibleExpandedIds } =
        useValues(logic)
    const { setOpen, setSearch, setExpandedIds, selectSource, refreshDatabaseSchema } = useActions(logic)
    const scrollRef = useRef<HTMLDivElement>(null)

    return (
        <LemonDropdown
            visible={open}
            onVisibilityChange={setOpen}
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={
                <div className="flex w-72 max-w-full flex-col gap-1" data-attr="bi-editor-data-source-picker">
                    <LemonInput
                        type="search"
                        fullWidth
                        size="small"
                        value={search}
                        onChange={setSearch}
                        placeholder="Search tables"
                        aria-label="Search tables"
                        data-attr="bi-editor-data-source-search"
                        autoFocus
                    />
                    {databaseLoading ? (
                        <div className="flex items-center gap-2 p-2 text-xs text-secondary">
                            <Spinner /> Loading tables
                        </div>
                    ) : databaseLoadError ? (
                        <div className="flex flex-col items-start gap-2 p-2 text-xs">
                            <span>Couldn't load tables.</span>
                            <LemonButton size="xsmall" type="secondary" onClick={refreshDatabaseSchema}>
                                Retry
                            </LemonButton>
                        </div>
                    ) : filteredTree.length ? (
                        <div className="max-h-96 overflow-y-auto" ref={scrollRef}>
                            <LemonTree
                                data={filteredTree}
                                virtualized
                                virtualizationScrollContainerRef={scrollRef}
                                expandedItemIds={visibleExpandedIds}
                                onSetExpandedItemIds={setExpandedIds}
                                onItemClick={(item) => item && selectSource(item.id)}
                                isItemActive={(item) =>
                                    !!config.source && item.id === getBIDataSourceKey(config.source)
                                }
                                renderItemIcon={(item) => (
                                    <TreeNodeDisplayIcon
                                        item={item}
                                        expandedItemIds={visibleExpandedIds}
                                        defaultNodeIcon={<IconDatabase />}
                                    />
                                )}
                            />
                        </div>
                    ) : (
                        <span className="p-2 text-xs text-secondary">
                            {search ? 'No matching tables' : 'No tables available for this connection'}
                        </span>
                    )}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                fullWidth
                icon={<IconDatabase />}
                sideIcon={<IconChevronDown />}
                truncate
                data-attr="bi-editor-data-source"
            >
                {config.source?.table ?? 'Select a table'}
            </LemonButton>
        </LemonDropdown>
    )
}
