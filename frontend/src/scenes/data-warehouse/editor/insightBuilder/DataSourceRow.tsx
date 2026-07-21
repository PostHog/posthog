import { useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { IconChevronDown, IconCode, IconDatabase } from '@posthog/icons'
import {
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxListFooter,
    ComboboxSeparator,
} from '@posthog/quill'

import { IconTableChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { escapeDottedHogQLIdentifier } from '~/queries/utils'

import { DataSource, outputPaneLogic } from '../outputPaneLogic'
import { sqlEditorLogic } from '../sqlEditorLogic'
import { insightBuilderLogic } from './insightBuilderLogic'

const CUSTOM_SQL = '__custom_sql__'
const ACTIONS_GROUP = '__actions__'

interface PickerGroup {
    value: string
    items: string[]
}

/**
 * The top "Data source" row of the builder: one searchable picker over everything you can build
 * on (views + warehouse tables), with "Write custom SQL" as the escape hatch. Picking Custom SQL
 * reveals the SQL editor passed as `children` (tree + query pane).
 */
export function DataSourceRow({ tabId, children }: { tabId: string; children: React.ReactNode }): JSX.Element {
    const { dataSource } = useValues(outputPaneLogic({ tabId }))
    const { setDataSource } = useActions(outputPaneLogic({ tabId }))
    const { baseViewName } = useValues(insightBuilderLogic({ tabId }))
    const { setQueryInput, runQuery } = useActions(sqlEditorLogic({ tabId }))
    const { dataWarehouseSavedQueries } = useValues(dataWarehouseViewsLogic)
    const { dataWarehouseTables } = useValues(databaseTableListLogic)

    const [open, setOpen] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const viewNames = useMemo(
        () => dataWarehouseSavedQueries.map((view) => view.name).sort((a, b) => a.localeCompare(b)),
        [dataWarehouseSavedQueries]
    )
    const warehouseNames = useMemo(
        () => dataWarehouseTables.map((table) => table.name).sort((a, b) => a.localeCompare(b)),
        [dataWarehouseTables]
    )
    const groups: PickerGroup[] = useMemo(
        () =>
            [
                { value: 'Views', items: viewNames },
                { value: 'Warehouse tables', items: warehouseNames },
                // Sentinel group so the escape hatch stays arrow-key navigable in the list
                { value: ACTIONS_GROUP, items: [CUSTOM_SQL] },
            ].filter((group) => group.items.length > 0),
        [viewNames, warehouseNames]
    )
    const viewNameSet = useMemo(() => new Set(viewNames), [viewNames])

    const onValueChange = (name: string | null): void => {
        if (!name) {
            return
        }
        if (name === CUSTOM_SQL) {
            setDataSource(DataSource.Sql)
            return
        }
        const query = `SELECT * FROM ${escapeDottedHogQLIdentifier(name)} LIMIT 100`
        setQueryInput(query)
        runQuery(query)
        // detectSelectAllTarget in refreshBase (fired by setDataSource) picks the object name up as baseView
        setDataSource(viewNameSet.has(name) ? DataSource.View : DataSource.Warehouse)
    }

    const selectedName = dataSource === DataSource.Sql ? null : baseViewName
    const triggerLabel = dataSource === DataSource.Sql ? 'Custom SQL' : (selectedName ?? 'Select a view or table')

    return (
        <div className="flex min-h-0 flex-1 flex-col border-b bg-surface-primary">
            <div className="flex items-center gap-3 px-3 py-2">
                <span className="text-xs font-semibold uppercase text-tertiary">Data source</span>
                <Combobox
                    items={groups}
                    open={open}
                    onOpenChange={setOpen}
                    value={selectedName}
                    onValueChange={onValueChange}
                >
                    <LemonButton
                        ref={triggerRef}
                        type="secondary"
                        size="small"
                        icon={dataSource === DataSource.Sql ? <IconCode /> : <IconTableChart />}
                        sideIcon={<IconChevronDown />}
                        onClick={() => setOpen((previous) => !previous)}
                        data-attr="sql-builder-data-source-trigger"
                    >
                        {triggerLabel}
                    </LemonButton>
                    <ComboboxContent anchor={triggerRef} className="w-90">
                        <ComboboxInput placeholder="Search views and tables" showTrigger={false} />
                        <ComboboxEmpty>No views or tables found</ComboboxEmpty>
                        <ComboboxList>
                            {(group: PickerGroup, index: number) =>
                                group.value === ACTIONS_GROUP ? (
                                    <ComboboxListFooter key="footer">
                                        <ComboboxItem value={CUSTOM_SQL}>
                                            <IconCode />
                                            Write custom SQL
                                        </ComboboxItem>
                                    </ComboboxListFooter>
                                ) : (
                                    <ComboboxGroup key={group.value} items={group.items}>
                                        <ComboboxLabel>{group.value}</ComboboxLabel>
                                        <ComboboxCollection>
                                            {(item: string) => (
                                                <ComboboxItem key={item} value={item}>
                                                    {group.value === 'Views' ? <IconTableChart /> : <IconDatabase />}
                                                    {item}
                                                </ComboboxItem>
                                            )}
                                        </ComboboxCollection>
                                        {index < groups.length - 1 && <ComboboxSeparator />}
                                    </ComboboxGroup>
                                )
                            }
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
            </div>

            {dataSource === null ? (
                <div className="px-3 pb-3 text-sm text-secondary">Choose a data source to start building.</div>
            ) : null}

            {dataSource === DataSource.Sql ? (
                <div className="flex min-h-0 flex-1 overflow-hidden border-t">{children}</div>
            ) : null}
        </div>
    )
}
