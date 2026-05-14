import clsx from 'clsx'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { faviconUrl } from '../common'
import { LiveAnimatedTable } from './LiveAnimatedTable'
import { DIRECT_REFERRER, type ReferrerItem, type TrafficSourceKind } from './LiveWebAnalyticsMetricsTypes'

const DIRECT_DISPLAY_NAME = 'Direct / None'
const RESOLVED_SOURCE_TOGGLE_TOOLTIP =
    'Use UTM, referrer, click ID, and in-app browser signals. Turn off to show raw $referring_domain.'

const SOURCE_KIND_META: Record<TrafficSourceKind, { label: string | null; tooltip: string }> = {
    utm: { label: 'UTM', tooltip: 'From utm_source.' },
    referrer: { label: 'Referrer', tooltip: 'From the browser referrer.' },
    click_id: { label: 'Inferred', tooltip: 'Inferred from click IDs.' },
    user_agent: { label: 'Inferred', tooltip: 'Inferred from in-app browser signals.' },
    direct: { label: null, tooltip: 'No source signal was present.' },
}

const displaySource = (source: string): string => {
    return source === DIRECT_REFERRER ? DIRECT_DISPLAY_NAME : source
}

const renderReferrerLabel = (item: ReferrerItem): { node: React.ReactNode; tooltipTitle: string } => {
    const isDirect = item.source === DIRECT_REFERRER
    const label = displaySource(item.source)
    const kindMeta = SOURCE_KIND_META[item.kind]
    const shouldRenderFavicon = !isDirect && /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(item.source)

    return {
        node: (
            <div className="flex items-center gap-2 min-w-0">
                {shouldRenderFavicon && (
                    <img
                        src={faviconUrl(item.source)}
                        alt=""
                        className="w-4 h-4 flex-shrink-0"
                        loading="lazy"
                        onError={(event) => {
                            event.currentTarget.style.display = 'none'
                        }}
                    />
                )}
                <span className={clsx('text-xs truncate', isDirect ? 'text-muted italic' : 'font-mono')}>{label}</span>
                {kindMeta.label && (
                    <LemonTag type="muted" size="small" className="flex-shrink-0">
                        {kindMeta.label}
                    </LemonTag>
                )}
            </div>
        ),
        tooltipTitle: `${label}. ${kindMeta.tooltip}`,
    }
}

interface LiveTopReferrersTableProps {
    referrers: ReferrerItem[]
    isLoading: boolean
    className?: string
    totalPageviews: number
    showResolvedSources: boolean
    setShowResolvedSources: (value: boolean) => void
}

export const LiveTopReferrersTable = ({
    referrers,
    isLoading,
    className,
    totalPageviews,
    showResolvedSources,
    setShowResolvedSources,
}: LiveTopReferrersTableProps): JSX.Element => (
    <LiveAnimatedTable
        items={referrers}
        keyExtractor={(item) => `${item.kind}:${item.source}`}
        viewsExtractor={(item) => item.views}
        renderLabel={renderReferrerLabel}
        title="Top sources (last 30 minutes)"
        titleAction={
            <LemonSwitch
                label={
                    <span className="flex items-center gap-1 text-xs">
                        Resolve sources
                        <Tooltip title={RESOLVED_SOURCE_TOGGLE_TOOLTIP} delayMs={0}>
                            <IconInfo className="text-muted-alt hover:text-default cursor-help" />
                        </Tooltip>
                    </span>
                }
                checked={showResolvedSources}
                onChange={setShowResolvedSources}
                size="xsmall"
                bordered
            />
        }
        columnLabel="Source"
        emptyMessage="No source data in the last 30 minutes"
        isLoading={isLoading}
        totalPageviews={totalPageviews}
        className={className}
    />
)
