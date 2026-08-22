import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function getErrorLabelForMaterializedView(error: string | null): JSX.Element | null {
    if (!error) {
        return null
    }

    const normalized = error.toLowerCase()

    if (normalized.includes('query returned no results')) {
        return (
            <span>
                Query returned no results for this view. This either means you haven't{' '}
                <Link to={urls.revenueSettings()} target="_blank" targetBlankIcon={false}>
                    configured Revenue Analytics
                </Link>{' '}
                properly (missing subscription properties) or the{' '}
                <Link to={urls.dataPipelinesNew('source')} target="_blank" targetBlankIcon={false}>
                    underlying source of data
                </Link>{' '}
                isn't correctly set-up.
            </span>
        )
    }

    if (normalized.includes('memory limit') || normalized.includes('too many rows')) {
        return (
            <span>
                This view used too much memory to materialize. Narrow the date range or filters in the query, or split
                it into smaller views, then try again.
            </span>
        )
    }

    if (normalized.includes('timeout') || normalized.includes('max_execution_time')) {
        return (
            <span>
                This view timed out while materializing. Simplify the query or reduce the data it scans, then try again.
            </span>
        )
    }

    if (
        normalized.includes('unknown column') ||
        normalized.includes('missing columns') ||
        normalized.includes('unknown identifier') ||
        normalized.includes("there's no column")
    ) {
        return (
            <span>
                This view references a column that no longer exists. Update the query to match the current schema of its
                source tables.
            </span>
        )
    }

    if (
        normalized.includes("doesn't exist") ||
        normalized.includes('does not exist') ||
        normalized.includes('unknown table')
    ) {
        return (
            <span>
                A source this view depends on is missing or failed to sync. Check its status on the{' '}
                <Link to={urls.pipelineStatus()} target="_blank" targetBlankIcon={false}>
                    data pipeline health page
                </Link>
                , then re-run the view.
            </span>
        )
    }

    return null
}
