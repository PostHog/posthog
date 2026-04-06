import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function getErrorLabelForMaterializedView(error: string | null): JSX.Element | null {
    if (!error) {
        return null
    }

    if (error.includes('Query returned no results')) {
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

    return null
}
