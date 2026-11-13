import { useActions, useValues } from 'kea'
import { Suspense, lazy } from 'react'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { retryImport } from 'lib/utils/retryImport'

import { FlagComparisonErrorBoundary } from '~/toolbar/floating/components/flags/FlagComparisonErrorBoundary'
import { flagComparisonLogic } from '~/toolbar/shared/flags/flagComparisonLogic'

// VisualImageDiffViewer is most of the comparison code, so the flags menu chunk loads it only when a comparison opens.
const FlagComparisonDiff = lazy(() =>
    retryImport(() => import('~/toolbar/shared/flags/FlagComparisonDiff')).then((m) => ({
        default: m.FlagComparisonDiff,
    }))
)

export function FlagComparisonModal(): JSX.Element {
    const { comparison, onCaptures, beforeCapture, afterCapture } = useValues(flagComparisonLogic)
    const { closeComparison, setAfterValue } = useActions(flagComparisonLogic)

    return (
        <LemonModal
            isOpen={!!comparison}
            onClose={closeComparison}
            forceAbovePopovers
            width="90vw"
            title={comparison ? `Compare ${comparison.flagKey}` : ''}
            description={
                afterCapture
                    ? `Before shows the page with the flag off. After shows it with ${
                          onCaptures.length > 1 ? `the ${afterCapture.label} variant` : 'the flag on'
                      }.`
                    : undefined
            }
        >
            {comparison && beforeCapture && afterCapture ? (
                <FlagComparisonErrorBoundary>
                    <Suspense
                        fallback={
                            <div className="flex justify-center p-4">
                                <Spinner className="text-2xl" />
                            </div>
                        }
                    >
                        <FlagComparisonDiff
                            before={beforeCapture}
                            after={afterCapture}
                            onCaptures={onCaptures}
                            identical={comparison.identical}
                            onAfterValueChange={setAfterValue}
                        />
                    </Suspense>
                </FlagComparisonErrorBoundary>
            ) : null}
        </LemonModal>
    )
}
