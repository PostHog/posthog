import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import {
    LemonButton,
    LemonDropdown,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { CatalogNodeDTOApi } from 'products/catalog/frontend/generated/api.schemas'

import { STATUS_COLOR, STATUS_LABEL } from './catalogConstants'
import { catalogListSceneLogic, type CatalogKindFilter, type CatalogStatusFilter } from './catalogListSceneLogic'
import { CatalogPageTabs } from './CatalogPageTabs'

export const scene: SceneExport = {
    component: CatalogListScene,
    logic: catalogListSceneLogic,
    productKey: ProductKey.CATALOG,
}

const KIND_OPTIONS: { value: CatalogKindFilter; label: string }[] = [
    { value: 'all', label: 'All kinds' },
    { value: 'warehouse_table', label: 'Warehouse table' },
    { value: 'saved_query', label: 'Saved query' },
    { value: 'system_table', label: 'System table' },
    { value: 'posthog_table', label: 'PostHog table' },
]

const STATUS_OPTIONS: { value: CatalogStatusFilter; label: string }[] = [
    { value: 'all', label: 'All statuses' },
    { value: 'proposed', label: STATUS_LABEL.proposed },
    { value: 'approved', label: STATUS_LABEL.approved },
    { value: 'official', label: STATUS_LABEL.official },
    { value: 'drift', label: STATUS_LABEL.drift },
]

export function CatalogListScene(): JSX.Element {
    const {
        nodes,
        filteredNodes,
        nodesLoading,
        searchTerm,
        kindFilter,
        statusFilter,
        tagFilter,
        availableTags,
        hasActiveFilters,
        syncing,
    } = useValues(catalogListSceneLogic)
    const { setSearchTerm, setKindFilter, setStatusFilter, setTagFilter, clearFilters, startSync } =
        useActions(catalogListSceneLogic)

    const tableColumns: LemonTableColumns<CatalogNodeDTOApi> = [
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => a.name.localeCompare(b.name),
            render: (_, node) => (
                <Link to={urls.catalogDefinition(node.id)} className="font-mono">
                    {node.name}
                </Link>
            ),
        },
        {
            title: 'Kind',
            key: 'kind',
            sorter: (a, b) => a.kind.localeCompare(b.kind),
            render: (_, node) => <span className="font-mono text-xs text-secondary">{node.kind}</span>,
        },
        {
            title: 'Domain',
            key: 'business_domain',
            render: (_, node) => node.business_domain ?? '—',
        },
        {
            title: 'Tags',
            key: 'tags',
            render: (_, node) =>
                node.tags.length === 0 ? (
                    '—'
                ) : (
                    <div className="flex flex-wrap gap-1">
                        {node.tags.map((tag) => (
                            <LemonTag key={tag} type="default">
                                {tag}
                            </LemonTag>
                        ))}
                    </div>
                ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, node) => (
                <LemonTag type={STATUS_COLOR[node.status] ?? 'default'}>
                    {STATUS_LABEL[node.status] ?? node.status}
                </LemonTag>
            ),
        },
    ]

    if (nodesLoading && nodes.length === 0) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-64" />
                <LemonSkeleton className="h-32 w-full" />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Semantic layer"
                description="Tables, saved queries, and system tables tracked by the semantic layer."
                resourceType={{ type: 'data_warehouse' }}
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={startSync}
                        loading={syncing}
                        disabledReason={syncing ? 'Sync already running' : undefined}
                    >
                        Sync
                    </LemonButton>
                }
            />
            <CatalogPageTabs activeTab="list" />
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    className="w-64"
                    placeholder="Search nodes by name"
                    value={searchTerm}
                    onChange={setSearchTerm}
                />
                <LemonSelect<CatalogKindFilter>
                    value={kindFilter}
                    onChange={(v) => setKindFilter(v ?? 'all')}
                    options={KIND_OPTIONS}
                    size="small"
                />
                <LemonSelect<CatalogStatusFilter>
                    value={statusFilter}
                    onChange={(v) => setStatusFilter(v ?? 'all')}
                    options={STATUS_OPTIONS}
                    size="small"
                />
                {availableTags.length > 0 && (
                    <LemonDropdown
                        closeOnClickInside={false}
                        matchWidth={false}
                        placement="bottom-end"
                        actionable
                        overlay={
                            <div className="max-w-100 deprecated-space-y-2">
                                <ul className="deprecated-space-y-px">
                                    {availableTags.map((tag) => {
                                        const checked = tagFilter.includes(tag)
                                        return (
                                            <li key={tag}>
                                                <LemonButton
                                                    fullWidth
                                                    role="menuitem"
                                                    size="small"
                                                    onClick={() =>
                                                        setTagFilter(
                                                            checked
                                                                ? tagFilter.filter((t) => t !== tag)
                                                                : [...tagFilter, tag]
                                                        )
                                                    }
                                                >
                                                    <span className="flex items-center gap-2">
                                                        <input
                                                            type="checkbox"
                                                            className="cursor-pointer"
                                                            checked={checked}
                                                            readOnly
                                                        />
                                                        <span>{tag}</span>
                                                    </span>
                                                </LemonButton>
                                            </li>
                                        )
                                    })}
                                    {tagFilter.length > 0 && (
                                        <>
                                            <div className="my-1 border-t" />
                                            <li>
                                                <LemonButton
                                                    fullWidth
                                                    role="menuitem"
                                                    size="small"
                                                    onClick={() => setTagFilter([])}
                                                    type="tertiary"
                                                >
                                                    Clear selection
                                                </LemonButton>
                                            </li>
                                        </>
                                    )}
                                </ul>
                            </div>
                        }
                    >
                        <LemonButton size="small" type="secondary" active={tagFilter.length > 0}>
                            {tagFilter.length > 0 ? `Tags (${tagFilter.length})` : 'Tags'}
                        </LemonButton>
                    </LemonDropdown>
                )}
                {hasActiveFilters && (
                    <LemonButton type="tertiary" size="small" onClick={clearFilters}>
                        Clear
                    </LemonButton>
                )}
                <span className="text-secondary text-xs ml-auto">
                    {filteredNodes.length === nodes.length
                        ? `${nodes.length} nodes`
                        : `${filteredNodes.length} of ${nodes.length} nodes`}
                </span>
            </div>
            <LemonTable
                dataSource={filteredNodes}
                columns={tableColumns}
                rowKey={(n) => n.id}
                emptyState={
                    <div className="text-secondary text-sm p-6 text-center">
                        {hasActiveFilters
                            ? 'No catalog nodes match the current filters.'
                            : 'No catalog nodes yet. Run the traversal workflow to populate it.'}
                    </div>
                }
            />
        </SceneContent>
    )
}
