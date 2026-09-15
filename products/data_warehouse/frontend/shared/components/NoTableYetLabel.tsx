import { IconInfo } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'

const APPLE_ANALYTICS_REPORTS_DOCS_URL =
    'https://developer.apple.com/documentation/appstoreconnectapi/downloading-analytics-reports'

export interface NoTableYetLabelProps {
    sourceType?: ExternalDataSourceType
}

function NoTableYetExplanation({ sourceType }: NoTableYetLabelProps): JSX.Element {
    if (sourceType === 'AppStoreConnect') {
        return (
            <>
                <p className="m-0">
                    The sync finished, but Apple has not made this report available yet. This is normal for a new
                    connection.
                </p>
                <p className="m-0 mt-2">
                    Apple can take a few days to produce the first analytics report. PostHog creates the table on the
                    first sync that returns rows. No action is needed.
                </p>
                <Link to={APPLE_ANALYTICS_REPORTS_DOCS_URL} target="_blank" className="mt-2 inline-block">
                    Read Apple's documentation on report timing
                </Link>
            </>
        )
    }
    return (
        <>
            <p className="m-0">
                The sync finished, but the source returned no rows, so there is no table to query yet.
            </p>
            <p className="m-0 mt-2">
                Some sources take time to make data available. PostHog creates the table on the first sync that returns
                rows. If you expect data now, check this source's settings and sync again.
            </p>
        </>
    )
}

export function NoTableYetLabel({ sourceType }: NoTableYetLabelProps): JSX.Element {
    return (
        <Tooltip interactive title={<NoTableYetExplanation sourceType={sourceType} />}>
            <span className="text-muted inline-flex items-center gap-1">
                No table yet
                <IconInfo className="text-muted-alt text-base" />
            </span>
        </Tooltip>
    )
}
