import { useValues } from 'kea'

import { LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { CatalogNodeDTOApi } from 'products/catalog/frontend/generated/api.schemas'

import { STATUS_COLOR, STATUS_LABEL } from './catalogConstants'
import { catalogListSceneLogic } from './catalogListSceneLogic'
import { CatalogPageTabs } from './CatalogPageTabs'

export const scene: SceneExport = {
    component: CatalogListScene,
    logic: catalogListSceneLogic,
    productKey: ProductKey.CATALOG,
}

export function CatalogListScene(): JSX.Element {
    const { nodes, nodesLoading } = useValues(catalogListSceneLogic)

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
            title: 'Columns',
            key: 'columns',
            sorter: (a, b) => a.columns.length - b.columns.length,
            render: (_, node) => node.columns.length,
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
            />
            <CatalogPageTabs activeTab="list" />
            <LemonTable
                dataSource={nodes}
                columns={tableColumns}
                rowKey={(n) => n.id}
                emptyState={
                    <div className="text-secondary text-sm p-6 text-center">
                        No catalog nodes yet. Run the traversal workflow to populate it.
                    </div>
                }
            />
        </SceneContent>
    )
}
