import { BindLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { SupermanHog } from 'lib/components/hedgehogs'
import { teamLogic } from 'scenes/teamLogic'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ErrorTrackingIssueList } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList'
import { ErrorTrackingIssueListSkeleton } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueListSkeleton'
import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'
import { ErrorTrackingIngestionPrompt } from 'products/error_tracking/frontend/components/SetupPrompt/SetupPrompt'

import {
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import { WidgetCardProductIntroduction } from '../../components/WidgetCardProductIntroduction/WidgetCardProductIntroduction'
import type { DashboardWidgetComponentProps } from '../registry'
import type { WidgetIssueMetadataDelta } from './applyWidgetIssueMetadataChange'
import { parseErrorTrackingWidgetConfig } from './errorTrackingWidgetConfigValidation'
import { errorTrackingWidgetLogic } from './errorTrackingWidgetLogic'
import { canConfigureErrorTrackingWidgetIssues } from './utils'

type ErrorTrackingWidgetResult = {
    results?: ErrorTrackingIssue[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
}

export function ErrorTrackingWidget({
    tileId,
    result,
    loading,
    config,
    onRefreshData,
    onApplyIssueMetadataChange,
    canMutateErrorTrackingIssues = false,
}: DashboardWidgetComponentProps): JSX.Element {
    if (loading) {
        return (
            <WidgetCardContent>
                <ErrorTrackingIssueListSkeleton rowCount={4} className="w-full" />
            </WidgetCardContent>
        )
    }

    return (
        <ErrorTrackingWidgetSetupGate>
            <BindLogic
                logic={errorTrackingWidgetLogic}
                props={{
                    tileId,
                    onApplyIssueMetadataChange: onApplyIssueMetadataChange
                        ? (issueId: string, delta: WidgetIssueMetadataDelta) => {
                              const parsed = parseErrorTrackingWidgetConfig(config)
                              onApplyIssueMetadataChange(issueId, delta, {
                                  statusFilter: parsed.status ?? 'active',
                                  assigneeFilter: parsed.assignee ?? null,
                              })
                          }
                        : undefined,
                    onRefreshData,
                }}
            >
                <ErrorTrackingWidgetBody
                    result={result}
                    config={config}
                    canMutateIssues={canMutateErrorTrackingIssues}
                />
            </BindLogic>
        </ErrorTrackingWidgetSetupGate>
    )
}

function ErrorTrackingWidgetSetupGate({ children }: { children: ReactNode }): JSX.Element {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(exceptionIngestionLogic)
    const { currentTeam } = useValues(teamLogic)

    if (hasSentExceptionEventLoading || !currentTeam) {
        return (
            <WidgetCardContent>
                <div className="flex justify-center">
                    <Spinner />
                </div>
            </WidgetCardContent>
        )
    }

    if (!canConfigureErrorTrackingWidgetIssues(currentTeam, hasSentExceptionEvent)) {
        return (
            <WidgetCardContent>
                <ErrorTrackingIngestionPrompt
                    className="border-none mb-0 mt-0 p-4"
                    introductionStacked
                    IntroductionComponent={WidgetCardProductIntroduction}
                    actionElementClassName="flex flex-col items-center gap-4"
                />
            </WidgetCardContent>
        )
    }

    return <>{children}</>
}

function ErrorTrackingWidgetBody({
    result,
    config,
    canMutateIssues,
}: {
    result: DashboardWidgetComponentProps['result']
    config: DashboardWidgetComponentProps['config']
    canMutateIssues: boolean
}): JSX.Element {
    const payload = result as ErrorTrackingWidgetResult | null | undefined
    const rows = payload?.results ?? []
    const orderBy = parseErrorTrackingWidgetConfig(config).orderBy

    if (rows.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="error-tracking-widget-empty-state"
                    >
                        <SupermanHog className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">All clear!</p>
                        <p className="m-0 text-sm text-muted">
                            No issues matched your filters. That's a good thing. Enjoy the quiet.
                        </p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <ErrorTrackingIssueList issues={rows} orderBy={orderBy} canMutateIssues={canMutateIssues} />
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={rows.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    hasMore={payload?.hasMore}
                    dataAttr="error-tracking-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
