import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton } from '@posthog/lemon-ui'

import { VisualImageDiffViewer } from 'lib/components/VisualImageDiffViewer'

import { flagComparisonLogic } from '~/toolbar/shared/flags/flagComparisonLogic'

export function FlagComparisonDiff(): JSX.Element | null {
    const { comparison, onCaptures, beforeCapture, afterCapture } = useValues(flagComparisonLogic)
    const { setAfterValue } = useActions(flagComparisonLogic)

    if (!comparison || !beforeCapture || !afterCapture) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {onCaptures.length > 1 ? (
                <LemonSegmentedButton
                    size="small"
                    value={String(afterCapture.value)}
                    onChange={setAfterValue}
                    options={onCaptures.map((capture) => ({
                        value: String(capture.value),
                        label: capture.label,
                        'data-attr': 'toolbar-flag-comparison-variant',
                    }))}
                />
            ) : null}
            {comparison.identical ? (
                <LemonBanner type="info">The page didn't change. It may only read flags when it loads.</LemonBanner>
            ) : null}
            <VisualImageDiffViewer
                baselineUrl={beforeCapture.url}
                currentUrl={afterCapture.url}
                diffUrl={null}
                diffPercentage={null}
                result={afterCapture.sameAsOff ? 'unchanged' : 'changed'}
                baselineWidth={beforeCapture.width}
                baselineHeight={beforeCapture.height}
                currentWidth={afterCapture.width}
                currentHeight={afterCapture.height}
                imageWidth={afterCapture.width}
                imageHeight={afterCapture.height}
            />
        </div>
    )
}
