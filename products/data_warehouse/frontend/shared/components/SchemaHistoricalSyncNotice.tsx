import { Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

const FREE_HISTORICAL_SYNC_DAYS = 7

export function SchemaHistoricalSyncNotice({ sourceCreatedAt }: { sourceCreatedAt: string }): JSX.Element {
    const freeWindowEnd = dayjs(sourceCreatedAt).add(FREE_HISTORICAL_SYNC_DAYS, 'day')
    const freeWindowActive = dayjs().isBefore(freeWindowEnd)

    if (freeWindowActive) {
        return (
            <LemonBanner type="info" className="min-h-[auto] my-2">
                <span className="text-sm">
                    This source's free historical sync window runs until {freeWindowEnd.format('MMM DD, YYYY')}. Any
                    schema you enable before then syncs its full history for free.
                </span>
            </LemonBanner>
        )
    }

    return (
        <LemonBanner type="warning" className="min-h-[auto] my-2">
            <span className="text-sm">
                This source's free historical sync window ended on {freeWindowEnd.format('MMM DD, YYYY')}. Enabling a
                schema now syncs its full history at standard rates.{' '}
                <Link to="https://posthog.com/docs/cdp/sources" target="_blank">
                    Learn more
                </Link>
            </span>
        </LemonBanner>
    )
}
