import clsx from 'clsx'
import { useValues } from 'kea'

import { IconBolt, IconDatabaseBolt } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export type PreAggregatedBadgeVariant = 'preagg' | 'precomputed'
export type PreAggregatedBadgePosition = 'top-right' | 'bottom-right'

// FAQ answer explaining what the pre-computed badge means.
const QUERY_ENGINE_DOCS_URL = 'https://posthog.com/docs/web-analytics/faq#what-does-the-pre-computed-badge-mean'

interface PreAggregatedBadgeProps {
    variant?: PreAggregatedBadgeVariant
    position?: PreAggregatedBadgePosition
    // Optional opt-out wired by the host (the web analytics page). Keeps this component scene-agnostic:
    // when omitted, the tooltip just drops the "always query live data" shortcut.
    onDisable?: () => void
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

function PrecomputedTooltip({ onDisable }: { onDisable?: () => void }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 max-w-xs">
            <span>Loaded from a pre-computed state instead of running a live query against all events.</span>
            <span>It should be very close to live data, but isn't guaranteed to be exact.</span>
            <span>
                <Link to={QUERY_ENGINE_DOCS_URL}>Learn more</Link>
                {onDisable && (
                    <>
                        {' · '}
                        <Link onClick={onDisable}>Always query live data</Link>
                    </>
                )}
            </span>
        </div>
    )
}

export function PreAggregatedBadge({
    variant = 'preagg',
    position = 'top-right',
    onDisable,
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
        <Tooltip
            interactive
            title={isPrecomputed ? <PrecomputedTooltip onDisable={onDisable} /> : <PreAggregatedTooltip />}
        >
            <div className={clsx('absolute z-10', POSITION_CLASS[position])}>
                <Icon className={iconClassName} />
            </div>
        </Tooltip>
    )
}
