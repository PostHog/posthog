import { useActions, useValues } from 'kea'
import { appMetricsSceneLogic } from './appMetricsSceneLogic'
import { Drawer } from 'lib/components/Drawer'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { TZLabel } from 'lib/components/TimezoneAware'
import { PaginationControl, usePaginationLocal } from 'lib/components/PaginationControl'
import { Tabs } from 'antd'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { IconChevronLeft, IconChevronRight, IconExpandMore } from 'lib/components/icons'

export function ErrorDetailsDrawer(): JSX.Element {
    const { errorDetails, errorDetailsDrawerError, errorDetailsLoading } = useValues(appMetricsSceneLogic)
    const { closeErrorDetailsDrawer } = useActions(appMetricsSceneLogic)

    return (
        <LemonModal
            isOpen={!!errorDetailsDrawerError}
            onClose={closeErrorDetailsDrawer}
            title={
                <div className="flex items-center justify-between">
                    <span>{errorDetails[0]?.error_type}</span>
                </div>
            }
            description={errorDetails[0]?.error_details?.error.message?.substring(0, 200)}
            footer={
                <div className="flex items-center justify-end gap-1">
                    <span>1 of 20 sampled errors</span>
                    <LemonButton icon={<IconChevronLeft />} />
                    <LemonButton icon={<IconChevronRight />} />
                </div>
            }
            width={'min(50vw, 80rem)'}
        >
            <div className="min-h-screen">
                {errorDetailsLoading ? <LemonSkeleton className="h-10" /> : <ErrorDetails />}
            </div>
        </LemonModal>
    )

    return (
        <Drawer
            visible={!!errorDetailsDrawerError}
            onClose={closeErrorDetailsDrawer}
            title={
                <div className="flex items-center justify-between">
                    <span>Viewing error details</span>
                    <div className="flex items-center gap-1">
                        <span>1 of 20 sampled errors</span>
                        <LemonButton icon={<IconChevronLeft />} />
                        <LemonButton icon={<IconChevronRight />} />
                    </div>
                </div>
            }
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
        <div className="flex flex-col overflow-hidden">
            <div className="flex-1 space-y-2">
                <div className="flex items-top justify-between gap-2">
                    <div>
                        <LemonLabel>When:</LemonLabel> <TZLabel time={activeErrorDetails.timestamp} showSeconds />
                    </div>

                    {/* <PaginationControl {...paginationState} nouns={['sample error', 'sample errors']} /> */}
                </div>

                {activeErrorDetails.error_details.eventCount && (
                    <div>
                        <LemonLabel>Event Count</LemonLabel>
                        <div>{activeErrorDetails.error_details.eventCount}</div>
                    </div>
                )}

                {activeErrorDetails.error_details.error.message && (
                    <>
                        <LemonLabel>Error message</LemonLabel>
                        <CodeSnippet wrap language={Language.JavaScript}>
                            {activeErrorDetails.error_details.error.message}
                        </CodeSnippet>
                    </>
                )}

                <LemonButton sideIcon={<IconExpandMore />} fullWidth type="secondary">
                    Event payload
                </LemonButton>

                <div className="border rounded">
                    <LemonButton className="m-1" sideIcon={<IconExpandMore />} fullWidth>
                        Stack trace
                    </LemonButton>

                    {activeErrorDetails.error_details.error.stack && (
                        <>
                            <CodeSnippet wrap language={Language.JavaScript}>
                                {activeErrorDetails.error_details.error.stack}
                            </CodeSnippet>
                        </>
                    )}
                </div>

                {/* {activeErrorDetails.error_details.event && (
                    <>
                        <LemonLabel>Event payload</LemonLabel>
                        <CodeSnippet language={Language.JSON}>
                            {JSON.stringify(activeErrorDetails.error_details.event, null, 2)}
                        </CodeSnippet>
                    </>
                )} */}
            </div>
        </div>
    )
}
