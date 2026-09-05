import { IconWarning } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { checkSelectorBreadth, checkSelectorFragilityCached } from '~/toolbar/utils/selectorQuality'

interface SelectorQualityWarningProps {
    selector?: string | null
    compact?: boolean
}

export function SelectorQualityWarning({ selector, compact = false }: SelectorQualityWarningProps): JSX.Element | null {
    const fragility = checkSelectorFragilityCached(selector)
    const breadth = checkSelectorBreadth(selector)

    let title: string
    let compactBody: JSX.Element
    let fullBody: JSX.Element
    if (fragility.isFragile) {
        title = 'Fragile selector'
        compactBody = (
            <>
                {fragility.reason} <code>{fragility.fragileSelector}</code>. Add a <code>data-*</code> attribute for
                stable tracking.
            </>
        )
        fullBody = (
            <>
                {fragility.reason} <code className="text-xs">{fragility.fragileSelector}</code>.{' '}
                <strong>Recommendation:</strong> Add a <code className="text-xs">data-*</code> attribute (e.g.{' '}
                <code className="text-xs">data-analytics</code>) for stable tracking.
            </>
        )
    } else if (breadth.isBroad) {
        title = 'Broad selector'
        compactBody = (
            <>
                {breadth.reason}, so this action can count clicks on other elements. Add an id or attribute like{' '}
                <code>data-attr</code> to target one element.
            </>
        )
        fullBody = (
            <>
                {breadth.reason}, so this action can count clicks on other elements. <strong>Recommendation:</strong>{' '}
                Add an id or attribute (e.g. <code className="text-xs">data-attr="signup"</code>) to target one element.
            </>
        )
    } else {
        return null
    }

    if (compact) {
        return (
            <div className="text-xs mt-1 text-primary">
                <IconWarning className="inline mr-1 text-warning" />
                {compactBody}
            </div>
        )
    }

    return (
        <LemonBanner type="warning">
            <div className="text-sm">
                <strong>{title}:</strong> {fullBody}{' '}
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
