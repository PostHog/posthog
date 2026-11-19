import { LemonBanner, LemonSegmentedButton } from '@posthog/lemon-ui'

import { ComparisonMode, VisualImageDiffViewer } from 'lib/components/VisualImageDiffViewer'

import type { FlagComparisonCapture } from './flagComparisonLogic'

export interface FlagComparisonDiffProps {
    before: FlagComparisonCapture
    after: FlagComparisonCapture
    /** More than one capture with the flag on means a multivariate flag, so the diff shows a variant picker. */
    onCaptures: FlagComparisonCapture[]
    identical: boolean
    onAfterValueChange: (value: string) => void
    /** Leave both out to let the viewer keep its own mode. */
    mode?: ComparisonMode
    onModeChange?: (mode: ComparisonMode) => void
}

export function FlagComparisonDiff({
    before,
    after,
    onCaptures,
    identical,
    onAfterValueChange,
    mode,
    onModeChange,
}: FlagComparisonDiffProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {onCaptures.length > 1 ? (
                <LemonSegmentedButton
                    size="small"
                    value={String(after.value)}
                    onChange={onAfterValueChange}
                    options={onCaptures.map((capture) => ({
                        value: String(capture.value),
                        label: capture.label,
                        'data-attr': 'toolbar-flag-comparison-variant',
                    }))}
                />
            ) : null}
            {identical ? (
                <LemonBanner type="info">The page didn't change. It may only read flags when it loads.</LemonBanner>
            ) : null}
            <VisualImageDiffViewer
                baselineUrl={before.url}
                currentUrl={after.url}
                diffUrl={null}
                diffPercentage={null}
                result={after.sameAsOff ? 'unchanged' : 'changed'}
                baselineWidth={before.width}
                baselineHeight={before.height}
                currentWidth={after.width}
                currentHeight={after.height}
                imageWidth={after.width}
                imageHeight={after.height}
                mode={mode}
                onModeChange={onModeChange}
            />
        </div>
    )
}
