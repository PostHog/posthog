import type { CSSProperties } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import type { ClusterMapHighlight, ClusterMapSize } from './clusterMapSeries'

export function ClusterMapControls({
    highlight,
    sizeBy,
    onHighlightChange,
    onSizeChange,
}: {
    highlight: ClusterMapHighlight
    sizeBy: ClusterMapSize
    onHighlightChange: (value: ClusterMapHighlight) => void
    onSizeChange: (value: ClusterMapSize) => void
}): JSX.Element {
    const pillStyle = { '--lemon-button-radius': '9999px' } as CSSProperties

    return (
        <div className="flex items-center justify-between flex-wrap gap-x-4 gap-y-2 mb-3">
            <div className="flex items-center gap-1" role="group" aria-label="Highlight">
                <span className="text-xs text-muted mr-1">Highlight</span>
                {(['cluster', 'errors'] as const).map((value) => (
                    <LemonButton
                        key={value}
                        size="xsmall"
                        type={highlight === value ? 'primary' : 'secondary'}
                        active={highlight === value}
                        className="[--lemon-button-bg-color-active:var(--color-accent-highlight-primary)]"
                        aria-pressed={highlight === value}
                        style={pillStyle}
                        onClick={() => onHighlightChange(value)}
                        data-attr="clusters-map-highlight"
                    >
                        {value === 'cluster' ? 'Cluster' : 'Errors'}
                    </LemonButton>
                ))}
            </div>
            <div className="flex items-center gap-1" role="group" aria-label="Size by">
                <span className="text-xs text-muted mr-1">Size by</span>
                {(['none', 'cost', 'latency'] as const).map((value) => (
                    <LemonButton
                        key={value}
                        size="xsmall"
                        type={sizeBy === value ? 'primary' : 'secondary'}
                        active={sizeBy === value}
                        className="[--lemon-button-bg-color-active:var(--color-accent-highlight-primary)]"
                        aria-pressed={sizeBy === value}
                        style={pillStyle}
                        onClick={() => onSizeChange(value)}
                        data-attr="clusters-map-size"
                    >
                        {value === 'none' ? 'None' : value === 'cost' ? 'Cost' : 'Latency'}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
