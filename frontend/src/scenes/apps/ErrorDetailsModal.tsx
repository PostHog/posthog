import { useState } from 'react'
import { useActions, useValues } from 'kea'
import { AppMetricErrorDetail, appMetricsSceneLogic } from './appMetricsSceneLogic'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { LemonButton } from 'lib/components/LemonButton'
import { IconChevronLeft, IconChevronRight, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { LemonModal } from 'lib/components/LemonModal'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function ErrorDetailsModal(): JSX.Element {
    const { errorDetails, errorDetailsModalError, errorDetailsLoading } = useValues(appMetricsSceneLogic)
    const { closeErrorDetailsModal } = useActions(appMetricsSceneLogic)
    const [page, setPage] = useState(0)

    const activeErrorDetails: AppMetricErrorDetail = errorDetails[page]

    return (
        <LemonModal
            isOpen={!!errorDetailsModalError}
            onClose={closeErrorDetailsModal}
            title={errorDetailsModalError}
            width={'min(50vw, 80rem)'}
            description={<span>{activeErrorDetails?.error_details?.error.message?.substring(0, 200)}</span>}
            footer={
                <div className="flex items-center justify-end gap-1 h-">
                    {errorDetailsLoading ? (
                        <LemonSkeleton className="1-10" />
                    ) : (
                        <>
                            <span>
                                {page + 1} of {errorDetails.length} sample{errorDetails.length > 1 ? 's' : ''}
                            </span>
                            <LemonButton
                                icon={<IconChevronLeft />}
                                onClick={() => setPage(page - 1)}
                                disabled={page == 0}
                            />
                            <LemonButton
                                icon={<IconChevronRight />}
                                onClick={() => setPage(page + 1)}
                                disabled={page == errorDetails.length - 1}
                            />
                        </>
                    )}
                </div>
            }
        >
            {!errorDetailsModalError || errorDetailsLoading ? (
                <LemonSkeleton className="h-10" />
            ) : (
                // eslint-disable-next-line react/forbid-dom-props
                <div className="flex flex-col space-y-2" style={{ height: '80vh' }}>
                    <div>
                        <LemonLabel>When:</LemonLabel> <TZLabel time={activeErrorDetails.timestamp} showSeconds />
                    </div>

                    {activeErrorDetails.error_details.eventCount && (
                        <div>
                            <LemonLabel>Event Count</LemonLabel>
                            <div>{activeErrorDetails.error_details.eventCount}</div>
                        </div>
                    )}

                    {activeErrorDetails.error_details.error.message && (
                        <CollapsibleSection title="Error message" defaultIsExpanded={true}>
                            <CodeSnippet wrap language={Language.JavaScript}>
                                {activeErrorDetails.error_details.error.message}
                            </CodeSnippet>
                        </CollapsibleSection>
                    )}

                    {activeErrorDetails.error_details.event && (
                        <CollapsibleSection title="Event payload" defaultIsExpanded={false}>
                            <CodeSnippet wrap language={Language.JSON}>
                                {JSON.stringify(activeErrorDetails.error_details.event, null, 2)}
                            </CodeSnippet>
                        </CollapsibleSection>
                    )}

                    {activeErrorDetails.error_details.error.stack && (
                        <CollapsibleSection title="Stack trace" defaultIsExpanded={false}>
                            <CodeSnippet wrap language={Language.JavaScript}>
                                {activeErrorDetails.error_details.error.stack}
                            </CodeSnippet>
                        </CollapsibleSection>
                    )}
                </div>
            )}
        </LemonModal>
    )
}

function CollapsibleSection(props: {
    title: string
    defaultIsExpanded: boolean
    children: React.ReactNode
}): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(props.defaultIsExpanded)

    return (
        <div className="bg-mid border rounded">
            <LemonButton
                status="stealth"
                fullWidth
                onClick={() => setIsExpanded(!isExpanded)}
                sideIcon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                title={isExpanded ? 'Show less' : 'Show more'}
                className="bg-mid"
            >
                {props.title}
            </LemonButton>
            {isExpanded && <div className="bg-light p-2">{props.children}</div>}
        </div>
    )
}
