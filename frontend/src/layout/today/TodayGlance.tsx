import { Suspense, lazy } from 'react'

import { retryImport } from 'lib/utils/retryImport'

import { TodayHoverCardFact } from './TodayHoverCardFact'
import { TodayObjectGlance } from './todayObjectGlances'

// The charts are most of the code the home page adds, and this card opens only on hover.
const TodaySparkline = lazy(() =>
    retryImport(() =>
        import('scenes/project-homepage/today/TodaySparkline').then((m) => ({ default: m.TodaySparkline }))
    )
)

export function TodayGlance({
    glance,
    formatNumber,
}: {
    glance: TodayObjectGlance
    formatNumber: (value: number) => string
}): JSX.Element {
    const { headline } = glance
    return (
        <>
            {headline && (
                <div className="flex flex-col gap-1">
                    <div className="flex min-w-0 items-baseline gap-1.5">
                        <span className="text-lg leading-6 font-semibold tabular-nums">{headline.value}</span>
                        <span className="min-w-0 truncate text-xs text-muted-foreground">{headline.caption}</span>
                    </div>
                    {headline.series.length > 1 && (
                        <div className="h-10">
                            <Suspense fallback={null}>
                                <TodaySparkline
                                    values={headline.series}
                                    labels={headline.labels}
                                    tone="neutral"
                                    emphasizeLast={1}
                                    formatValue={headline.formatValue ?? formatNumber}
                                />
                            </Suspense>
                        </div>
                    )}
                </div>
            )}
            {glance.description && (
                <p className="m-0 line-clamp-2 text-xs text-muted-foreground">{glance.description}</p>
            )}
            {glance.facts.map(([label, value]) => (
                <TodayHoverCardFact key={label} label={label}>
                    {value}
                </TodayHoverCardFact>
            ))}
        </>
    )
}
