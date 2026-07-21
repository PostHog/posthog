import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

export type PickerKind = 'view' | 'warehouse'

interface PickerGroup {
    label: string
    items: { name: string; label: string }[]
}

function useViewGroups(search: string): PickerGroup[] {
    const { dataWarehouseSavedQueries, dataWarehouseSavedQueryFolders } = useValues(dataWarehouseViewsLogic)
    return useMemo(() => {
        const term = search.trim().toLowerCase()
        const folderName = (id?: string | null): string =>
            dataWarehouseSavedQueryFolders.find((folder) => folder.id === id)?.name ?? 'Ungrouped'
        const byFolder = new Map<string, { name: string; label: string }[]>()
        for (const view of dataWarehouseSavedQueries) {
            if (term && !view.name.toLowerCase().includes(term)) {
                continue
            }
            const group = folderName(view.folder_id)
            const items = byFolder.get(group) ?? []
            items.push({ name: view.name, label: view.name })
            byFolder.set(group, items)
        }
        return [...byFolder.entries()]
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([label, items]) => ({ label, items }))
    }, [dataWarehouseSavedQueries, dataWarehouseSavedQueryFolders, search])
}

function useWarehouseGroups(search: string): PickerGroup[] {
    const { dataWarehouseSources } = useValues(sourcesDataLogic)
    return useMemo(() => {
        const term = search.trim().toLowerCase()
        return (dataWarehouseSources?.results ?? [])
            .map((source) => {
                const items = source.schemas
                    .map((schema) => schema.table)
                    .filter((table): table is NonNullable<typeof table> => !!table)
                    .map((table) => ({ name: table.hogql_name ?? table.name, label: table.name }))
                    .filter((item) => !term || item.name.toLowerCase().includes(term))
                return { label: source.prefix || source.source_type, items }
            })
            .filter((group) => group.items.length > 0)
    }, [dataWarehouseSources, search])
}

function PickerBody({ kind, onPick }: { kind: PickerKind; onPick: (name: string) => void }): JSX.Element {
    const [search, setSearch] = useState('')
    const viewGroups = useViewGroups(search)
    const warehouseGroups = useWarehouseGroups(search)
    const groups = kind === 'view' ? viewGroups : warehouseGroups

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                placeholder={kind === 'view' ? 'Search views' : 'Search warehouse tables'}
                value={search}
                onChange={setSearch}
                autoFocus
            />
            <div className="max-h-[50vh] min-h-40 overflow-y-auto">
                {groups.length === 0 ? (
                    <div className="p-4 text-center text-sm text-secondary">
                        {kind === 'view' ? 'No views found' : 'No warehouse tables found'}
                    </div>
                ) : (
                    groups.map((group) => (
                        <div key={group.label} className="mb-2">
                            <div className="px-2 py-1 text-xs font-semibold uppercase text-tertiary">{group.label}</div>
                            {group.items.map((item) => (
                                <LemonButton key={item.name} fullWidth onClick={() => onPick(item.name)}>
                                    {item.label}
                                </LemonButton>
                            ))}
                        </div>
                    ))
                )}
            </div>
        </div>
    )
}

export function DataSourcePickerModal({
    kind,
    isOpen,
    onClose,
    onPick,
}: {
    kind: PickerKind
    isOpen: boolean
    onClose: () => void
    onPick: (name: string) => void
}): JSX.Element {
    const { loadDataWarehouseSavedQueries } = useActions(dataWarehouseViewsLogic)
    const { loadSources } = useActions(sourcesDataLogic)

    const manageUrl = kind === 'view' ? urls.dataOps('views') : urls.sources()
    const manageLabel = kind === 'view' ? 'Manage views' : 'Manage connectors'

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={kind === 'view' ? 'Choose a view' : 'Choose a warehouse table'}
            width={560}
            footer={
                <div className="flex w-full items-center justify-between">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={() => (kind === 'view' ? loadDataWarehouseSavedQueries() : loadSources())}
                    >
                        Refresh
                    </LemonButton>
                    <Link to={manageUrl} target="_blank">
                        <LemonButton size="small" type="secondary" sideIcon={<IconExternal />}>
                            {manageLabel}
                        </LemonButton>
                    </Link>
                </div>
            }
        >
            <PickerBody
                kind={kind}
                onPick={(name) => {
                    onPick(name)
                    onClose()
                }}
            />
        </LemonModal>
    )
}
