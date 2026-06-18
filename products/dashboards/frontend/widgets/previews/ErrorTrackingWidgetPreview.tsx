import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ErrorTrackingIssueList } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList'

import { errorTrackingSampleIssues } from '../../components/WidgetCard/widgetOverviewStoryFixtures'

const PREVIEW_ISSUES = errorTrackingSampleIssues as ErrorTrackingIssue[]

export function ErrorTrackingWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none shadow-sm">
            <ErrorTrackingIssueList issues={PREVIEW_ISSUES} />
        </div>
    )
}
