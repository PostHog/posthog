import { useEffect } from 'react'

import { IconWarning, IconX } from '@posthog/icons'
import { LemonBanner, LemonCollapse } from '@posthog/lemon-ui'

import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import {
    SelectorQuality,
    SelectorQualityResult,
    analyzeSelectorQualityCached,
    generateSuggestedAttribute,
} from '~/toolbar/utils/selectorQuality'

interface SelectorQualityWarningProps {
    selector?: string | null
    element?: HTMLElement
    compact?: boolean
    /** Minimum severity to show warning. 'warning' shows both warnings and fragile, 'fragile' only shows fragile */
    minSeverity?: 'warning' | 'fragile'
}

function shouldShowWarning(quality: SelectorQuality, minSeverity: 'warning' | 'fragile'): boolean {
    if (quality === 'good') {
        return false
    }
    if (quality === 'fragile') {
        return true
    }
    return minSeverity === 'warning'
}

export function SelectorQualityWarning({
    selector,
    element,
    compact = false,
    minSeverity = 'fragile',
}: SelectorQualityWarningProps): JSX.Element | null {
    const quality = selector ? analyzeSelectorQualityCached(selector) : null
    const shouldShow = quality && shouldShowWarning(quality.quality, minSeverity)

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

    const isFragile = quality.quality === 'fragile'
    const bannerType = isFragile ? 'error' : 'warning'
    const StatusIcon = isFragile ? IconX : IconWarning

    if (compact) {
        const issueText = quality.issues[0]?.description || 'Fragile selector detected'
        const recommendation = quality.recommendations[0] || 'Add a data-posthog attribute to your element'

        return (
            <div className="flex flex-row gap-2 items-center bg-border-light p-2 rounded">
                <StatusIcon className={`text-xl shrink-0 ${isFragile ? 'text-danger' : 'text-warning'}`} />
                <div className="text-primary text-xs grow">
                    {issueText}. {recommendation}.{' '}
                    <button
                        onClick={() => window.open('https://posthog.com/docs/toolbar#2-element-filters', '_blank')}
                        className="text-link underline cursor-pointer bg-transparent border-0 p-0"
                    >
                        Learn more
                    </button>
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
                    <strong>{isFragile ? 'Fragile selector detected' : 'Selector could be improved'}</strong>
                    <p className="text-sm mt-1">This selector may break when your page structure changes.</p>
                </div>

                {quality.issues.length > 0 && (
                    <LemonCollapse
                        defaultActiveKey={isFragile ? 'issues' : undefined}
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
                    <button
                        onClick={() => window.open('https://posthog.com/docs/toolbar#2-element-filters', '_blank')}
                        className="text-link underline cursor-pointer bg-transparent border-0 p-0"
                    >
                        Learn more about selector best practices
                    </button>
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

    const isFragile = quality.quality === 'fragile'
    const StatusIcon = isFragile ? IconX : IconWarning
    const title = `Selector quality: ${quality.quality}\n${quality.issues.map((i) => `• ${i.description}`).join('\n')}`

    return (
        <span className="ml-2 cursor-help" title={title}>
            <StatusIcon className={isFragile ? 'text-danger' : 'text-warning'} />
        </span>
    )
}
