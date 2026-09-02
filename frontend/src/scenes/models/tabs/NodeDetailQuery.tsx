import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { urls } from 'scenes/urls'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

function QueryAction({
    node,
    savedQuery,
}: {
    node: DataModelingNode
    savedQuery: DataWarehouseSavedQuery
}): JSX.Element {
    if (node.type === 'endpoint') {
        // An endpoint node carries the versioned view name (`my_endpoint_v3`), but the endpoint
        // route resolves the plain name and takes the version as a search param.
        const versionMatch = node.name.match(/^(.+)_v(\d+)$/)
        const to = versionMatch
            ? urls.endpoint(versionMatch[1], parseInt(versionMatch[2], 10))
            : urls.endpoint(node.name)
        return (
            <LemonButton type="secondary" size="small" to={to}>
                Open endpoint
            </LemonButton>
        )
    }

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.WarehouseObjects}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={savedQuery.user_access_level}
        >
            <LemonButton
                type="secondary"
                size="small"
                to={urls.sqlEditor({ view_id: savedQuery.id })}
                data-attr="node-detail-edit-in-sql-editor"
            >
                Edit in SQL editor
            </LemonButton>
        </AccessControlAction>
    )
}

export function NodeDetailQuery({ id }: { id: string }): JSX.Element {
    const { node, savedQuery, savedQueryLoading, savedQueryError } = useValues(nodeDetailSceneLogic({ id }))
    const { loadSavedQuery } = useActions(nodeDetailSceneLogic({ id }))

    if (savedQueryLoading && !savedQuery) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    if (savedQueryError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadSavedQuery }}>
                Couldn't load this model's query.
            </LemonBanner>
        )
    }

    const queryString = savedQuery?.query?.query
    const columns = savedQuery?.columns ?? []

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <h3 className="mb-0">SQL</h3>
                    {node && savedQuery && <QueryAction node={node} savedQuery={savedQuery} />}
                </div>
                {queryString ? (
                    <CodeSnippet language={Language.SQL} maxLinesWithoutExpansion={20} compact thing="query">
                        {queryString}
                    </CodeSnippet>
                ) : (
                    <p className="mb-0 text-secondary">This model has no query.</p>
                )}
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Columns ({columns.length})</h3>
                <LemonTable
                    size="small"
                    dataSource={columns}
                    rowKey="name"
                    nouns={['column', 'columns']}
                    emptyState="Columns appear after the view runs."
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, column: DatabaseSchemaField) => (
                                <span className="font-mono">{column.name}</span>
                            ),
                        },
                        {
                            title: 'Type',
                            key: 'type',
                            render: (_, column: DatabaseSchemaField) => column.type,
                        },
                    ]}
                />
            </div>
        </div>
    )
}
