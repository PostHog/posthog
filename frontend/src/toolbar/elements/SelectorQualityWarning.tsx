import { IconWarning } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { checkSelectorFragilityCached } from '~/toolbar/utils/selectorQuality'

interface SelectorQualityWarningProps {
    selector?: string | null
    compact?: boolean
}

export function SelectorQualityWarning({ selector, compact = false }: SelectorQualityWarningProps): JSX.Element | null {
    const result = checkSelectorFragilityCached(selector)

    if (!result.isFragile) {
        return null
    }

    if (compact) {
        return (
            <div className="text-xs mt-1 text-primary">
                <IconWarning className="inline mr-1 text-warning" />
                {result.reason} <code>{result.fragileSelector}</code>. Add a <code>data-*</code> attribute for stable
                tracking.
            </div>
        )
    }

    return (
        <LemonBanner type="warning">
            <div className="text-sm">
                <strong>Fragile selector:</strong> {result.reason}{' '}
                <code className="text-xs">{result.fragileSelector}</code>. <strong>Recommendation:</strong> Add a{' '}
                <code className="text-xs">data-*</code> attribute (e.g. <code className="text-xs">data-analytics</code>)
                for stable tracking.{' '}
                <button
                    onClick={() => window.open('https://posthog.com/docs/toolbar#2-element-filters', '_blank')}
                    className="text-link underline cursor-pointer bg-transparent border-0 p-0"
                >
                    Learn more
                </button>
            </div>
        </LemonBanner>
    )
}

interface SelectorQualityBadgeProps {
    selector?: string | null
}

export function SelectorQualityBadge({ selector }: SelectorQualityBadgeProps): JSX.Element | null {
    const result = checkSelectorFragilityCached(selector)

    if (!result.isFragile) {
        return null
    }

    return (
        <span className="ml-2 cursor-help" title={`Fragile selector: ${result.reason}`}>
            <IconWarning className="text-warning" />
        </span>
    )
}
