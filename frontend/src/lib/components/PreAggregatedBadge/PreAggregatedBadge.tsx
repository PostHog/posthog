import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconBolt, IconDatabaseBolt } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

export type PreAggregatedBadgeVariant = 'preagg' | 'precomputed'
export type PreAggregatedBadgePosition = 'top-right' | 'bottom-right'

// FAQ answer explaining what the pre-computed badge means.
const QUERY_ENGINE_DOCS_URL = 'https://posthog.com/docs/web-analytics/faq#what-does-the-pre-computed-badge-mean'

interface PreAggregatedBadgeProps {
    variant?: PreAggregatedBadgeVariant
    position?: PreAggregatedBadgePosition
}

const POSITION_CLASS: Record<PreAggregatedBadgePosition, string> = {
    'top-right': 'top-2 right-2',
    'bottom-right': 'bottom-2 right-2',
}

function PreAggregatedTooltip(): JSX.Element {
    return (
        <span>
            Optimized with our new query engine. <Link to={QUERY_ENGINE_DOCS_URL}>Learn more</Link>
        </span>
    )
}

function PrecomputedTooltip(): JSX.Element {
    const { setUseWebAnalyticsPrecompute } = useActions(webAnalyticsLogic)

    return (
        <div className="flex flex-col gap-1 max-w-xs">
            <span>
                Loaded from a pre-computed roll-up dataset — freshly recomputed by our new query engine instead of
                running a live query.
            </span>
            <span>It should be very close to live data, typically within ~1%, but isn't guaranteed to be exact.</span>
            <span>
                <Link to={QUERY_ENGINE_DOCS_URL}>Learn more</Link>
                {' · '}
                <Link onClick={() => setUseWebAnalyticsPrecompute(false)}>Always query live data</Link>
            </span>
        </div>
    )
}

export function PreAggregatedBadge({
    variant = 'preagg',
    position = 'top-right',
}: PreAggregatedBadgeProps = {}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const isPrecomputed = variant === 'precomputed'

    // The precompute kill switch only governs the pre-computed roll-up indicator. The pre-aggregated
    // ("new query engine") badge is controlled upstream by its own settings flag and must stay visible.
    if (isPrecomputed && !featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_PRECOMPUTE_TOGGLE]) {
        return null
    }

    const Icon = isPrecomputed ? IconDatabaseBolt : IconBolt
    const iconClassName = isPrecomputed ? 'text-muted w-4 h-4' : 'text-warning w-4 h-4'

    return (
        <Tooltip interactive title={isPrecomputed ? <PrecomputedTooltip /> : <PreAggregatedTooltip />}>
            <div className={clsx('absolute z-10', POSITION_CLASS[position])}>
                <Icon className={iconClassName} />
            </div>
        </Tooltip>
    )
}
