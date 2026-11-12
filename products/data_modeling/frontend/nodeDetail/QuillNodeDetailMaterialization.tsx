import { useActions, useValues } from 'kea'

import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Skeleton,
    Text,
} from '@posthog/quill'

import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { QuillMaterializationRunHistory } from './QuillMaterializationRunHistory'
import { QuillMaterializationSettings } from './QuillMaterializationSettings'

function MaterializationSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-4" aria-busy="true" data-attr="materialization-loading">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-8 w-full max-w-96" />
            <Skeleton className="h-5 w-full max-w-80" />
            <Skeleton className="h-24 w-full" />
        </div>
    )
}

export function QuillNodeDetailMaterialization({ id }: { id: string }): JSX.Element | null {
    const {
        node,
        savedQuery: sceneSavedQuery,
        savedQueryError,
        savedQueryLoading,
    } = useValues(nodeDetailSceneLogic({ id }))
    const { loadSavedQuery } = useActions(nodeDetailSceneLogic({ id }))
    const kind = node?.type === 'endpoint' ? 'endpoint' : 'view'
    const jobsLogic = materializationJobsLogic({ viewId: node?.saved_query_id ?? '', kind })
    const { savedQuery: panelSavedQuery, savedQueryLoading: panelSavedQueryLoading } = useValues(jobsLogic)
    const { loadSavedQuery: reloadPanelSavedQuery, loadDataModelingJobs } = useActions(jobsLogic)

    const retry = (): void => {
        loadSavedQuery()
        if (node?.saved_query_id) {
            reloadPanelSavedQuery()
            loadDataModelingJobs()
        }
    }

    if (savedQueryLoading && !sceneSavedQuery) {
        return <MaterializationSkeleton />
    }

    if (savedQueryError) {
        return (
            <Empty className="rounded-lg border border-border">
                <EmptyHeader>
                    <EmptyTitle>Couldn't load materialization settings</EmptyTitle>
                    <EmptyDescription>
                        Try again to load this model's refresh settings and run history.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={retry} loading={savedQueryLoading}>
                        Retry
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    if (!sceneSavedQuery) {
        return null
    }

    return (
        <div className="@container/materialization flex flex-col gap-4" data-attr="materialization-status-panel">
            <div className="flex flex-col gap-1">
                <Heading size="base" render={<h3 className="m-0" />}>
                    Materialization
                </Heading>
                <Text size="xs" variant="muted" className="m-0">
                    Store this model's query results and refresh them on a schedule so other queries can use them.
                </Text>
            </div>
            {panelSavedQuery ? (
                <>
                    <QuillMaterializationSettings savedQuery={panelSavedQuery} kind={kind} />
                    <QuillMaterializationRunHistory
                        viewId={panelSavedQuery.id}
                        kind={kind}
                        materialized={!!panelSavedQuery.is_materialized}
                        showRefreshMode={kind !== 'endpoint' && !!panelSavedQuery.has_incremental_history}
                    />
                </>
            ) : (
                panelSavedQueryLoading && <MaterializationSkeleton />
            )}
        </div>
    )
}
