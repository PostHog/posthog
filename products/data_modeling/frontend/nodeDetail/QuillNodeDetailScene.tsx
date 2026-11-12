import { useValues } from 'kea'
import { router } from 'kea-router'

import { Button, Skeleton, Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import { AccessDenied } from 'lib/components/AccessDenied'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { AccessControlLevel, AccessControlResourceType, ActivityScope } from '~/types'

import type { NodeDetailDataQualitySubject, NodeDetailSceneTab } from './nodeDetailSceneLogic'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { QuillNodeDetailHeader } from './QuillNodeDetailHeader'
import { QuillNodeDetailLineage } from './QuillNodeDetailLineage'
import { QuillNodeDetailMaterialization } from './QuillNodeDetailMaterialization'
import { QuillNodeDetailOverview } from './QuillNodeDetailOverview'
import { QuillNodeDetailQuery } from './QuillNodeDetailQuery'
import { QuillNodeDetailTests } from './QuillNodeDetailTests'
import { QuillNodeDetailTestsTabLabel } from './QuillNodeDetailTestsTabLabel'

const TAB_LABELS: Record<NodeDetailSceneTab, string> = {
    query: 'Query',
    lineage: 'Lineage',
    materialization: 'Materialization',
    'data-quality': 'Data quality',
    history: 'History',
}

function TabLabel({
    tab,
    dataQualitySubject,
}: {
    tab: NodeDetailSceneTab
    dataQualitySubject: NodeDetailDataQualitySubject | null
}): JSX.Element {
    if (tab === 'data-quality' && dataQualitySubject) {
        return <QuillNodeDetailTestsTabLabel {...dataQualitySubject} />
    }
    return <>{TAB_LABELS[tab]}</>
}

function TabPanel({
    id,
    tab,
    savedQueryId,
}: {
    id: string
    tab: NodeDetailSceneTab
    savedQueryId: string
}): JSX.Element {
    switch (tab) {
        case 'query':
            return <QuillNodeDetailQuery id={id} />
        case 'lineage':
            return <QuillNodeDetailLineage id={id} />
        case 'materialization':
            return <QuillNodeDetailMaterialization id={id} />
        case 'history':
            return (
                <ActivityLog
                    scope={[ActivityScope.DATA_WAREHOUSE_SAVED_QUERY, ActivityScope.DATA_QUALITY_CHECK]}
                    id={savedQueryId}
                />
            )
        case 'data-quality':
            return <QuillNodeDetailTests id={id} />
    }
}

export function QuillNodeDetailScene({ id }: { id: string }): JSX.Element {
    const {
        node,
        savedQueryDeleted,
        nodeLoading,
        availableTabs,
        effectiveTab,
        visitedTabs,
        dataQualitySubject,
        modelMetadata,
        modelListUrl,
    } = useValues(nodeDetailSceneLogic({ id }))

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so this page isn't available." />
        )
    }

    if (!node) {
        if (nodeLoading) {
            return (
                <SceneContent>
                    <QuillNodeDetailHeader id={id} />
                    <Skeleton className="h-8 w-96 max-w-full" />
                    <Skeleton className="h-64 w-full" />
                </SceneContent>
            )
        }
        return <NotFound object="model" />
    }

    if (savedQueryDeleted) {
        return (
            <NotFound
                object="model"
                caption={
                    <>
                        This model was deleted. Go back to{' '}
                        <Button variant="link" size="inline" render={<LinkPrimitive to={modelListUrl} />}>
                            Tables & views
                        </Button>
                        .
                    </>
                }
            />
        )
    }

    return (
        <SceneContent>
            <QuillNodeDetailHeader id={id} />
            <QuillNodeDetailOverview id={id} metadata={modelMetadata} />
            {!effectiveTab ? (
                <Skeleton className="h-8 w-96 max-w-full" />
            ) : (
                availableTabs.length > 1 && (
                    <Tabs
                        value={effectiveTab}
                        onValueChange={(tab: NodeDetailSceneTab) => router.actions.push(urls.nodeDetail(id, tab))}
                        data-quill
                    >
                        <div className="border-b border-border">
                            <TabsList variant="line" aria-label="Model sections">
                                {availableTabs.map((tab) => (
                                    <TabsTrigger key={tab} value={tab} data-attr={`node-detail-${tab}-tab`}>
                                        <TabLabel tab={tab} dataQualitySubject={dataQualitySubject} />
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                        </div>
                    </Tabs>
                )
            )}
            {availableTabs
                .filter((tab) =>
                    tab === 'history' ? tab === effectiveTab : visitedTabs.includes(tab) || tab === effectiveTab
                )
                .map((tab) => (
                    <div key={tab} className={tab === effectiveTab ? 'flex flex-1 flex-col' : 'hidden'}>
                        <TabPanel id={id} tab={tab} savedQueryId={node.saved_query_id ?? ''} />
                    </div>
                ))}
        </SceneContent>
    )
}
