import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

export function NodeDetailQuery({ id }: { id: string }): JSX.Element {
    const { savedQuery, savedQueryLoading, savedQueryError } = useValues(nodeDetailSceneLogic({ id }))
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
                {queryString ? (
                    <CodeSnippet
                        language={Language.SQL}
                        className="[&_pre]:max-h-96 [&_pre]:overflow-auto"
                        thing="query"
                    >
                        {queryString}
                    </CodeSnippet>
                ) : (
                    <p className="mb-0 text-secondary">This model has no query.</p>
                )}
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Columns</h3>
                <LemonTable
                    size="small"
                    key={id}
                    pagination={{ pageSize: 10, useUrl: false }}
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
