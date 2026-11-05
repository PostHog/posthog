import { useActions, useValues } from 'kea'
import { Suspense, lazy } from 'react'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { retryImport } from 'lib/utils/retryImport'

import { flagComparisonLogic } from '~/toolbar/shared/flags/flagComparisonLogic'

// VisualImageDiffViewer is most of the comparison code, so the flags menu chunk loads it only when a comparison opens.
const FlagComparisonDiff = lazy(() =>
    retryImport(() => import('~/toolbar/floating/components/flags/FlagComparisonDiff')).then((m) => ({
        default: m.FlagComparisonDiff,
    }))
)

export function FlagComparisonModal(): JSX.Element {
    const { comparison, onCaptures, afterCapture } = useValues(flagComparisonLogic)
    const { closeComparison } = useActions(flagComparisonLogic)

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
            {comparison ? (
                <Suspense
                    fallback={
                        <div className="flex justify-center p-4">
                            <Spinner className="text-2xl" />
                        </div>
                    }
                >
                    <FlagComparisonDiff />
                </Suspense>
            ) : null}
        </LemonModal>
    )
}
