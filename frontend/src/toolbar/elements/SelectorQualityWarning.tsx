import { useEffect } from 'react'

import { LemonBanner, LemonCollapse, Link } from '@posthog/lemon-ui'

import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import {
    SelectorQualityResult,
    analyzeSelectorQualityCached,
    generateSuggestedAttribute,
} from '~/toolbar/utils/selectorQuality'

type MinSeverity = 'warning' | 'fragile'

interface SelectorQualityWarningProps {
    selector?: string | null
    element?: HTMLElement
    compact?: boolean
    minSeverity?: MinSeverity
}

export function SelectorQualityWarning({
    selector,
    element,
    compact = false,
    minSeverity = 'fragile',
}: SelectorQualityWarningProps): JSX.Element | null {
    // Analyze selector quality (must be before any conditional returns to satisfy React Hooks rules)
    const quality = selector ? analyzeSelectorQualityCached(selector) : null

    // Check if quality meets minimum severity threshold
    const severityOrder: Record<MinSeverity, number> = {
        warning: 1,
        fragile: 2,
    }

    const shouldShow =
        quality &&
        (quality.quality === 'fragile' ||
            (quality.quality === 'warning' && severityOrder[minSeverity] <= severityOrder.warning))

    // Track when warning is shown (must be before any conditional returns)
    useEffect(() => {
        if (shouldShow && quality && selector) {
            toolbarPosthogJS.capture('toolbar_selector_quality_warning_shown', {
                quality: quality.quality,
                selector: selector,
                issues: quality.issues.map((i) => i.type),
                has_nth_child: selector.includes(':nth-'),
                depth: (selector.match(/>/g) || []).length + selector.split(/\s+/).length - 1,
            })
        }
    }, [shouldShow, quality, selector])

    // Early returns after all hooks
    if (!shouldShow || !quality) {
        return null
    }

    const bannerType = quality.quality === 'fragile' ? 'error' : 'warning'

    if (compact) {
        const icon = quality.quality === 'fragile' ? '❌' : '⚠️'

        // Get the main issue description
        const firstIssue = quality.issues[0]
        const issueText = firstIssue?.description || 'Fragile selector detected'

        // Get the first recommendation and format it
        const firstRecommendation = quality.recommendations[0] || 'Add a data-posthog attribute to your element'

        return (
            <div className="flex flex-row gap-2 items-center bg-border-light p-2 rounded">
                <div className="text-warning text-xl shrink-0">{icon}</div>
                <div className="text-primary text-xs grow">
                    {issueText}. {firstRecommendation}.{' '}
                    <Link
                        to="https://posthog.com/docs/toolbar#2-element-filters"
                        target="_blank"
                        disableClientSideRouting
                        className="text-link underline"
                    >
                        Learn more
                    </Link>
                </div>
            </div>
        )
    }

    const suggestedAttribute = element ? generateSuggestedAttribute(element) : null
    const elementTag = element?.tagName.toLowerCase() || 'element'

    return (
        <LemonBanner type={bannerType}>
            <div className="space-y-2">
                <div>
                    <strong>
                        {quality.quality === 'fragile' ? 'Fragile selector detected' : 'Selector could be improved'}
                    </strong>
                    <p className="text-sm mt-1">This selector may break when your page structure changes.</p>
                </div>

                {quality.issues.length > 0 && (
                    <LemonCollapse
                        defaultActiveKey={quality.quality === 'fragile' ? 'issues' : undefined}
                        panels={[
                            {
                                key: 'issues',
                                header: 'Why is this fragile?',
                                content: (
                                    <ul className="list-disc list-inside space-y-1 text-sm">
                                        {quality.issues.map((issue, i) => (
                                            <li key={i}>{issue.description}</li>
                                        ))}
                                    </ul>
                                ),
                            },
                        ]}
                    />
                )}

                {quality.recommendations.length > 0 && (
                    <div className="space-y-2">
                        <strong className="text-sm">Recommendation:</strong>
                        {suggestedAttribute && element ? (
                            <div className="space-y-2">
                                <p className="text-sm">Add a data-posthog attribute to your element:</p>
                                <pre className="p-2 bg-bg-3000 rounded text-xs overflow-x-auto">
                                    {`<${elementTag} data-posthog="${suggestedAttribute}"${
                                        element.className ? ` class="${element.className}"` : ''
                                    }>`}
                                    {element.textContent && element.textContent.length <= 50
                                        ? `\n  ${element.textContent.trim()}\n`
                                        : '\n  ...\n'}
                                    {`</${elementTag}>`}
                                </pre>
                                <p className="text-xs text-muted">
                                    Then use the toolbar to re-select the element with the new attribute.
                                </p>
                            </div>
                        ) : (
                            <ul className="list-disc list-inside space-y-1 text-sm">
                                {quality.recommendations.map((rec, i) => (
                                    <li key={i}>{rec}</li>
                                ))}
                            </ul>
                        )}
                    </div>
                )}

                <div className="mt-3">
                    <Link
                        to="https://posthog.com/docs/toolbar#2-element-filters"
                        target="_blank"
                        disableClientSideRouting
                        className="text-link underline"
                    >
                        Learn more about selector best practices
                    </Link>
                </div>
            </div>
        </LemonBanner>
    )
}

interface SelectorQualityBadgeProps {
    quality: SelectorQualityResult
}

export function SelectorQualityBadge({ quality }: SelectorQualityBadgeProps): JSX.Element | null {
    if (quality.quality === 'good') {
        return null
    }

    const icon = quality.quality === 'fragile' ? '❌' : '⚠️'
    const title = `Selector quality: ${quality.quality}\n${quality.issues.map((i) => `• ${i.description}`).join('\n')}`

    return (
        <span className="ml-2 text-base cursor-help" title={title}>
            {icon}
        </span>
    )
}
