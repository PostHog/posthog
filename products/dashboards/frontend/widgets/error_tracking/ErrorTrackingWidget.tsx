import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { SupermanHog } from 'lib/components/hedgehogs'
import { teamLogic } from 'scenes/teamLogic'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ErrorTrackingIssueList } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList'
import { ErrorTrackingIssueListSkeleton } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueListSkeleton'
import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'
import { ErrorTrackingIngestionPrompt } from 'products/error_tracking/frontend/components/SetupPrompt/SetupPrompt'

import { WidgetCardBodyMessage, WidgetCardContent } from '../../components/WidgetCard'
import { WidgetCardProductIntroduction } from '../../components/WidgetCardProductIntroduction/WidgetCardProductIntroduction'
import type { DashboardWidgetComponentProps } from '../registry'
import { canConfigureErrorTrackingWidgetIssues } from './utils'

type ErrorTrackingWidgetResult = {
    results?: ErrorTrackingIssue[]
    hasMore?: boolean
    limit?: number
}

export function ErrorTrackingWidget({ result, loading }: DashboardWidgetComponentProps): JSX.Element {
    if (loading) {
        return (
            <WidgetCardContent>
                <ErrorTrackingIssueListSkeleton rowCount={4} className="w-full" />
            </WidgetCardContent>
        )
    }

    return (
        <ErrorTrackingWidgetSetupGate>
            <ErrorTrackingWidgetBody result={result} />
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

function ErrorTrackingWidgetBody({ result }: { result: DashboardWidgetComponentProps['result'] }): JSX.Element {
    const payload = result as ErrorTrackingWidgetResult | null | undefined
    const rows = payload?.results ?? []

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
        <WidgetCardContent>
            <ErrorTrackingIssueList issues={rows} />
        </WidgetCardContent>
    )
}
