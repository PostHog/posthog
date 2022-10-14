import React from 'react'
import { useActions, useValues } from 'kea'
import { appMetricsSceneLogic } from './appMetricsSceneLogic'
import { Drawer } from 'lib/components/Drawer'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { TZLabel } from 'lib/components/TimezoneAware'
import { PaginationControl, usePaginationLocal } from 'lib/components/PaginationControl'
import { Tabs } from 'antd'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'

export function ErrorDetailsDrawer(): JSX.Element {
    const { errorDetailsDrawerError, errorDetailsLoading } = useValues(appMetricsSceneLogic)
    const { closeErrorDetailsDrawer } = useActions(appMetricsSceneLogic)

    return (
        <Drawer
            visible={!!errorDetailsDrawerError}
            onClose={closeErrorDetailsDrawer}
            title={`Viewing error details: ${errorDetailsDrawerError}`}
            width={'min(50vw, 80rem)'}
            destroyOnClose
        >
            {errorDetailsLoading ? <LemonSkeleton className="h-10" /> : <ErrorDetails />}
        </Drawer>
    )
}

function ErrorDetails(): JSX.Element {
    const { errorDetails } = useValues(appMetricsSceneLogic)
    const paginationState = usePaginationLocal(errorDetails, { pageSize: 1 })

    const [activeErrorDetails] = paginationState.dataSourcePage

    return (
        <div>
            <PaginationControl {...paginationState} nouns={['sample error', 'sample errors']} />

            <Tabs>
                <Tabs.TabPane tab="Overview" key="overview">
                    <div>
                        <LemonLabel>Error:</LemonLabel> {activeErrorDetails.error_type}
                    </div>
                    {activeErrorDetails.error_details.error.message && (
                        <div>
                            <LemonLabel>Error message:</LemonLabel> {activeErrorDetails.error_details.error.message}
                        </div>
                    )}
                    <div>
                        <LemonLabel>When:</LemonLabel> <TZLabel time={activeErrorDetails.timestamp} showSeconds />
                    </div>
                    {activeErrorDetails.error_details.eventCount && (
                        <div>
                            <LemonLabel>Error message:</LemonLabel> {activeErrorDetails.error_details.error.message}
                        </div>
                    )}
                </Tabs.TabPane>
                {activeErrorDetails.error_details.event && (
                    <Tabs.TabPane tab="Event" key="event">
                        <CodeSnippet language={Language.JSON}>
                            {JSON.stringify(activeErrorDetails.error_details.event, null, 2)}
                        </CodeSnippet>
                    </Tabs.TabPane>
                )}
                {activeErrorDetails.error_details.error.stack && (
                    <Tabs.TabPane tab="Stack trace" key="stacktrace">
                        <CodeSnippet wrap language={Language.JavaScript}>
                            {activeErrorDetails.error_details.error.stack}
                        </CodeSnippet>
                    </Tabs.TabPane>
                )}
            </Tabs>
        </div>
    )
}
