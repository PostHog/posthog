import clsx from 'clsx'

import { faviconUrl } from '../common'
import { LiveAnimatedTable } from './LiveAnimatedTable'
import { DIRECT_REFERRER, ReferrerItem } from './LiveWebAnalyticsMetricsTypes'

const DIRECT_DISPLAY_NAME = 'Direct / None'

const displayReferrer = (referrer: string): string => {
    return referrer === DIRECT_REFERRER ? DIRECT_DISPLAY_NAME : referrer
}

const renderReferrerLabel = (item: ReferrerItem): { node: React.ReactNode; tooltipTitle: string } => {
    const isDirect = item.referrer === DIRECT_REFERRER
    const label = displayReferrer(item.referrer)
    return {
        node: (
            <div className="flex items-center gap-2 min-w-0">
                {!isDirect && (
                    <img
                        src={faviconUrl(item.referrer)}
                        alt=""
                        className="w-4 h-4 flex-shrink-0"
                        loading="lazy"
                        onError={(e) => {
                            ;(e.target as HTMLImageElement).style.display = 'none'
                        }}
                    />
                )}
                <span className={clsx('text-xs truncate', isDirect ? 'text-muted italic' : 'font-mono')}>{label}</span>
            </div>
        ),
        tooltipTitle: label,
    }
}

interface LiveTopReferrersTableProps {
    referrers: ReferrerItem[]
    isLoading: boolean
    className?: string
    totalPageviews: number
}

export const LiveTopReferrersTable = ({
    referrers,
    isLoading,
    className,
    totalPageviews,
}: LiveTopReferrersTableProps): JSX.Element => (
    <LiveAnimatedTable
        items={referrers}
        keyExtractor={(item) => item.referrer}
        viewsExtractor={(item) => item.views}
        renderLabel={renderReferrerLabel}
        title="Top referrers (last 30 minutes)"
        columnLabel="Referrer"
        emptyMessage="No referrer data in the last 30 minutes"
        isLoading={isLoading}
        totalPageviews={totalPageviews}
        className={className}
    />
)
